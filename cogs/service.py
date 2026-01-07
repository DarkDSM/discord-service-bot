import discord
from discord.ext import commands, tasks
from discord import ui
import datetime
import json
import os
import asyncio
from datetime import datetime, timedelta

# Fichier pour stocker les services
SERVICE_FILE = "service_data.json"

# IDs fixes pour les boutons - toujours les mêmes
BUTTON_IDS = {
    "prise": "service_prise_button",
    "fin": "service_fin_button"
}

class ServiceView(ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)  # Pas de timeout pour la persistance
        self.cog = cog
    
    @discord.ui.button(label='🟢 Prise de service', style=discord.ButtonStyle.success, custom_id=BUTTON_IDS["prise"])
    async def prise_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.gestion_prise_service(interaction)
    
    @discord.ui.button(label='🔴 Fin de service', style=discord.ButtonStyle.danger, custom_id=BUTTON_IDS["fin"])
    async def fin_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.gestion_fin_service(interaction)

class Service(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.en_service = {}  # {user_id: {"debut": datetime, "session_start": datetime}}
        self.historique = {}  # {user_id: {date: temps_en_secondes}}
        self.services_termines = {}  # {user_id: {"temps_total": sec, "heure_debut": str, "heure_fin": str, "date": str}}
        self.tableau_messages = {}  # {channel_id: message_id}
        self.jours_semaine = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
        self.charger_donnees()
        print("✅ Cog Service chargé")
        
        # Démarrer les tâches
        self.update_tableau.start()
        self.reset_quotidien.start()
    
    # ========== GESTION DES DONNÉES ==========
    
    def get_date_du_jour(self):
        """Retourne la date d'aujourd'hui au format YYYY-MM-DD"""
        return datetime.now().strftime("%Y-%m-%d")
    
    def get_datetime_now(self):
        """Retourne le datetime actuel"""
        return datetime.now()
    
    def charger_donnees(self):
        """Charge les données depuis le fichier JSON"""
        try:
            if os.path.exists(SERVICE_FILE):
                with open(SERVICE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                    # Charger en_service
                    self.en_service = {}
                    for user_id, service_data in data.get('en_service', {}).items():
                        self.en_service[user_id] = {
                            "debut": datetime.fromisoformat(service_data["debut"]),
                            "session_start": datetime.fromisoformat(service_data["session_start"])
                        }
                    
                    # Charger historique
                    self.historique = data.get('historique', {})
                    
                    # Charger services terminés
                    self.services_termines = data.get('services_termines', {})
                    
                    print(f"✅ Données chargées: {len(self.historique)} utilisateurs, {len(self.en_service)} en service")
            else:
                self.en_service = {}
                self.historique = {}
                self.services_termines = {}
                print("✅ Fichier de données créé")
        except Exception as e:
            print(f"❌ Erreur chargement données: {e}")
            self.en_service = {}
            self.historique = {}
            self.services_termines = {}
    
    def sauvegarder_donnees(self):
        """Sauvegarde les données dans le fichier JSON"""
        try:
            # Convertir en_service pour sauvegarde
            en_service_save = {}
            for user_id, data in self.en_service.items():
                en_service_save[user_id] = {
                    "debut": data["debut"].isoformat(),
                    "session_start": data["session_start"].isoformat()
                }
            
            data = {
                'en_service': en_service_save,
                'historique': self.historique,
                'services_termines': self.services_termines
            }
            
            with open(SERVICE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"❌ Erreur sauvegarde données: {e}")
    
    def format_duree(self, secondes):
        """Formate une durée en secondes en texte lisible (heures:minutes:secondes)"""
        heures = secondes // 3600
        minutes = (secondes % 3600) // 60
        sec = secondes % 60
        
        if heures > 0:
            return f"{heures}h{minutes:02d}m{sec:02d}s"
        elif minutes > 0:
            return f"{minutes}m{sec:02d}s"
        else:
            return f"{sec}s"
    
    def format_duree_court(self, secondes):
        """Formate une durée en version courte pour les embeds"""
        heures = secondes // 3600
        minutes = (secondes % 3600) // 60
        sec = secondes % 60
        
        if heures > 0:
            return f"{heures}h{minutes:02d}m{sec:02d}s"
        else:
            return f"{minutes}m{sec:02d}s"
    
    def format_duree_live(self, secondes):
        """Formate une durée pour l'affichage live (format dynamique)"""
        heures = secondes // 3600
        minutes = (secondes % 3600) // 60
        sec = secondes % 60
        
        if heures > 0:
            return f"**{heures}:{minutes:02d}:{sec:02d}**"
        else:
            return f"**{minutes:02d}:{sec:02d}**"
    
    def get_temps_cumule_du_jour(self, user_id):
        """Récupère le temps déjà cumulé aujourd'hui"""
        today = self.get_date_du_jour()
        if user_id in self.historique and today in self.historique[user_id]:
            return self.historique[user_id][today]
        return 0
    
    # ========== TÂCHES AUTOMATIQUES ==========
    
    @tasks.loop(seconds=1)  # Mise à jour toutes les secondes !
    async def update_tableau(self):
        """Met à jour tous les tableaux de service en temps réel"""
        for channel_id, message_id in list(self.tableau_messages.items()):
            try:
                channel = self.bot.get_channel(channel_id)
                if not channel:
                    del self.tableau_messages[channel_id]
                    continue
                
                message = await channel.fetch_message(message_id)
                if not message:
                    del self.tableau_messages[channel_id]
                    continue
                
                # Vérifier si le message appartient bien au bot
                if message.author.id != self.bot.user.id:
                    del self.tableau_messages[channel_id]
                    continue
                
                # Mettre à jour l'embed du tableau
                embed = self.creer_embed_tableau_live()
                await message.edit(embed=embed, view=ServiceView(self))
                
            except discord.NotFound:
                # Message supprimé
                del self.tableau_messages[channel_id]
            except discord.Forbidden:
                # Pas la permission
                del self.tableau_messages[channel_id]
            except Exception as e:
                print(f"❌ Erreur mise à jour tableau {channel_id}: {e}")
    
    @update_tableau.before_loop
    async def before_update_tableau(self):
        """Attend que le bot soit prêt"""
        await self.bot.wait_until_ready()
        print("⏱️ Tâche de mise à jour du tableau démarrée")
    
    @tasks.loop(seconds=60)  # Vérifie toutes les minutes
    async def reset_quotidien(self):
        """Réinitialise les données quotidiennes à minuit"""
        now = self.get_datetime_now()
        today = now.strftime("%Y-%m-%d")
        
        # Vérifier si on est passé à minuit
        if hasattr(self, 'derniere_date'):
            if self.derniere_date != today:
                print(f"⏰ Nouveau jour détecté: {today}")
                # Réinitialiser les services terminés du jour précédent
                self.services_termines = {}
                self.sauvegarder_donnees()
                print("✅ Services terminés réinitialisés pour le nouveau jour")
        
        self.derniere_date = today
    
    @reset_quotidien.before_loop
    async def before_reset_quotidien(self):
        """Attend que le bot soit prêt"""
        await self.bot.wait_until_ready()
        self.derniere_date = self.get_date_du_jour()
        print("🔄 Tâche de réinitialisation quotidienne démarrée")
    
    # ========== CRÉATION DES EMBEDS ==========
    
    def creer_embed_tableau_live(self):
        """Crée l'embed du tableau de service avec timers en direct"""
        now = self.get_datetime_now()
        embed = discord.Embed(
            title="📋 TABLEAU DE SERVICE - EN DIRECT ⏱️",
            description="Cliquez sur les boutons ci-dessous pour gérer votre service :",
            color=discord.Color.blue(),
            timestamp=now
        )
        
        # Colonne GAUCHE : Personnes en service
        service_list = []
        for uid, service_data in self.en_service.items():
            user = self.bot.get_user(int(uid))
            if user:
                session_start = service_data["session_start"]
                
                # Temps de la session en cours (LIVE !)
                temps_session_sec = (now - session_start).seconds
                temps_session_live = self.format_duree_live(temps_session_sec)
                
                # Temps total du jour (historique + session en cours)
                temps_historique = self.get_temps_cumule_du_jour(uid)
                temps_total_sec = temps_historique + temps_session_sec
                temps_total = self.format_duree_court(temps_total_sec)
                
                service_list.append(
                    f"**{user.display_name}**\n"
                    f"⏱️ **Direct:** {temps_session_live}\n"
                    f"📊 **Total jour:** {temps_total}\n"
                    f"🕐 **Début:** {session_start.strftime('%H:%M:%S')}\n"
                    f"━━━━━━━━━━━━━━━━━━"
                )
        
        embed.add_field(
            name="🟢 **PRISE DE SERVICE**",
            value="\n".join(service_list) if service_list else "*Aucune personne en service*",
            inline=True
        )
        
        # Colonne DROITE : Services terminés aujourd'hui
        fin_list = []
        
        # Récupérer les services terminés d'aujourd'hui
        today = self.get_date_du_jour()
        for uid, data in self.services_termines.items():
            # Vérifier que c'est pour aujourd'hui
            if data.get('date') == today:
                user = self.bot.get_user(int(uid))
                if user:
                    fin_list.append(
                        f"**{user.display_name}**\n"
                        f"⏱️ **Session:** {data['temps_session']}\n"
                        f"📊 **Total jour:** {data['temps_total']}\n"
                        f"🕐 **Début:** {data['heure_debut']} | **Fin:** {data['heure_fin']}\n"
                        f"━━━━━━━━━━━━━━━━━━"
                    )
        
        # Limiter à 5 derniers
        fin_list = fin_list[-5:] if fin_list else ["*Aucun service terminé aujourd'hui*"]
        
        embed.add_field(
            name="🔴 **FIN DE SERVICE**",
            value="\n".join(fin_list),
            inline=True
        )
        
        # Statistiques du jour
        total_today_sec = 0
        personnes_en_service = len(self.en_service)
        personnes_terminees = len([uid for uid, data in self.services_termines.items() 
                                  if data.get('date') == today])
        total_personnes = personnes_en_service + personnes_terminees
        
        # Calculer le temps total du jour
        for user_id, jours in self.historique.items():
            if today in jours:
                total_today_sec += jours[today]
        
        if total_personnes > 0:
            total_formate = self.format_duree(total_today_sec)
            
            stats_text = f"• **{total_personnes}** personne(s) aujourd'hui\n"
            stats_text += f"• **{personnes_en_service}** en service\n"
            stats_text += f"• **{personnes_terminees}** terminé(s)\n"
            stats_text += f"• **{total_formate}** cumulé"
            
            embed.add_field(
                name="📊 **STATISTIQUES DU JOUR**",
                value=stats_text,
                inline=False
            )
        
        # Date et heure
        embed.set_footer(
            text=f"📅 {today} | ⏱️ Mis à jour: {now.strftime('%H:%M:%S')} | Mise à jour chaque seconde !"
        )
        
        return embed
    
    # ========== GESTION DES BOUTONS ==========
    
    async def gestion_prise_service(self, interaction: discord.Interaction):
        """Gère la prise de service"""
        user_id = str(interaction.user.id)
        today = self.get_date_du_jour()
        now = self.get_datetime_now()
        
        # Vérifier si déjà en service
        if user_id in self.en_service:
            session_start = self.en_service[user_id]["session_start"]
            temps_session_sec = (now - session_start).seconds
            temps_session = self.format_duree(temps_session_sec)
            
            # Calculer le temps total du jour
            temps_historique = self.get_temps_cumule_du_jour(user_id)
            temps_total_sec = temps_historique + temps_session_sec
            temps_total = self.format_duree(temps_total_sec)
            
            await interaction.response.send_message(
                f"❌ {interaction.user.mention}, vous êtes déjà en service !\n"
                f"**Session en cours:** {temps_session}\n"
                f"**Total aujourd'hui:** {temps_total}",
                ephemeral=True
            )
            return
        
        # Retirer des services terminés si présent
        if user_id in self.services_termines:
            del self.services_termines[user_id]
        
        # Récupérer le temps déjà fait aujourd'hui
        temps_deja_fait = self.get_temps_cumule_du_jour(user_id)
        temps_deja_fait_formate = self.format_duree(temps_deja_fait)
        
        # Si l'utilisateur a déjà un historique aujourd'hui, on repart du dernier cumul
        if temps_deja_fait > 0:
            message_info = f"**Reprise de service** - Cumul actuel: {temps_deja_fait_formate}"
        else:
            message_info = f"**Nouveau service**"
        
        # Enregistrer la prise de service
        self.en_service[user_id] = {
            "debut": now,  # Heure du début global
            "session_start": now  # Heure de début de cette session
        }
        
        await interaction.response.send_message(
            f"✅ {interaction.user.mention} a pris son service !\n"
            f"{message_info}\n"
            f"**Temps déjà fait aujourd'hui:** {temps_deja_fait_formate}\n"
            f"**Heure de début:** {now.strftime('%H:%M:%S')}\n\n"
            f"⏱️ **Votre nom apparaît maintenant dans 'Prise de service'**",
            ephemeral=True
        )
        
        # Sauvegarder
        self.sauvegarder_donnees()
    
    async def gestion_fin_service(self, interaction: discord.Interaction):
        """Gère la fin de service"""
        user_id = str(interaction.user.id)
        today = self.get_date_du_jour()
        now = self.get_datetime_now()
        
        # Vérifier si en service
        if user_id not in self.en_service:
            # Vérifier si l'utilisateur a déjà terminé aujourd'hui
            if user_id in self.services_termines and self.services_termines[user_id].get('date') == today:
                data = self.services_termines[user_id]
                await interaction.response.send_message(
                    f"📊 {interaction.user.mention}, vous avez déjà terminé votre service aujourd'hui.\n"
                    f"**Session:** {data['temps_session']}\n"
                    f"**Total jour:** {data['temps_total']}\n"
                    f"**Début:** {data['heure_debut']} | **Fin:** {data['heure_fin']}",
                    ephemeral=True
                )
            else:
                # Vérifier le temps déjà fait aujourd'hui
                temps_deja_fait = self.get_temps_cumule_du_jour(user_id)
                if temps_deja_fait > 0:
                    temps_formate = self.format_duree(temps_deja_fait)
                    await interaction.response.send_message(
                        f"📊 {interaction.user.mention}, vous n'êtes pas actuellement en service.\n"
                        f"**Temps fait aujourd'hui:** {temps_formate}",
                        ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        f"❌ {interaction.user.mention}, vous n'êtes pas en service !",
                        ephemeral=True
                    )
            return
        
        # Récupérer les données du service
        service_data = self.en_service.pop(user_id)
        session_start = service_data["session_start"]
        debut_global = service_data["debut"]
        
        # Calculer la durée de cette session
        duree_session_sec = (now - session_start).seconds
        duree_session_formatee = self.format_duree(duree_session_sec)
        
        # Initialiser l'historique si nécessaire
        if user_id not in self.historique:
            self.historique[user_id] = {}
        
        if today not in self.historique[user_id]:
            self.historique[user_id][today] = 0
        
        # Ajouter la durée de la session au temps cumulé du jour
        ancien_temps = self.historique[user_id][today]
        self.historique[user_id][today] += duree_session_sec
        
        # Formater le temps total du jour
        temps_total_sec = self.historique[user_id][today]
        temps_total_formate = self.format_duree_court(temps_total_sec)
        temps_total_long = self.format_duree(temps_total_sec)
        
        # Enregistrer dans les services terminés
        self.services_termines[user_id] = {
            'temps_session': duree_session_formatee,
            'temps_total': temps_total_formate,
            'heure_debut': session_start.strftime('%H:%M:%S'),
            'heure_fin': now.strftime('%H:%M:%S'),
            'date': today
        }
        
        # Calculer la durée totale depuis le premier début
        duree_totale_sec = (now - debut_global).seconds
        duree_totale_formatee = self.format_duree(duree_totale_sec)
        
        # Sauvegarder
        self.sauvegarder_donnees()
        
        # Envoyer le message de confirmation
        await interaction.response.send_message(
            f"✅ {interaction.user.mention} a terminé son service !\n"
            f"**Durée session:** {duree_session_formatee}\n"
            f"**Total aujourd'hui:** {temps_total_long}\n"
            f"**Début session:** {session_start.strftime('%H:%M:%S')}\n"
            f"**Fin session:** {now.strftime('%H:%M:%S')}\n"
            f"**Durée totale depuis le début:** {duree_totale_formatee}\n\n"
            f"📋 **Votre nom apparaît maintenant dans 'Fin de service'**",
            ephemeral=True
        )
    
    # ========== COMMANDES TEXTUELLES ==========
    
    @commands.command(name='PS', aliases=['service', 'tableau'])
    async def ps_command(self, ctx):
        """Affiche le tableau de service avec boutons et timers en direct"""
        # Supprimer le message de commande
        try:
            await ctx.message.delete()
        except:
            pass
        
        # Vérifier s'il y a déjà un tableau dans ce channel
        if ctx.channel.id in self.tableau_messages:
            try:
                old_message = await ctx.channel.fetch_message(self.tableau_messages[ctx.channel.id])
                await old_message.delete()
            except:
                pass
        
        # Créer le premier embed
        embed = self.creer_embed_tableau_live()
        message = await ctx.send(embed=embed, view=ServiceView(self))
        
        # Enregistrer le message pour les mises à jour
        self.tableau_messages[ctx.channel.id] = message.id
        
        print(f"📋 Tableau créé par {ctx.author.name} dans #{ctx.channel.name}")
    
    @commands.command(name='refresh_tableau')
    async def refresh_tableau_command(self, ctx):
        """Force le rafraîchissement du tableau"""
        # Supprimer le message de commande
        try:
            await ctx.message.delete()
        except:
            pass
        
        if ctx.channel.id in self.tableau_messages:
            try:
                message = await ctx.channel.fetch_message(self.tableau_messages[ctx.channel.id])
                embed = self.creer_embed_tableau_live()
                await message.edit(embed=embed, view=ServiceView(self))
                await ctx.send("✅ Tableau rafraîchi !", delete_after=5)
            except Exception as e:
                await ctx.send(f"❌ Erreur: {e}", delete_after=10)
        else:
            await ctx.send("❌ Aucun tableau dans ce channel. Utilisez `!PS`", delete_after=10)
    
    @commands.command(name='stop_tableau')
    async def stop_tableau_command(self, ctx):
        """Arrête la mise à jour du tableau dans ce channel"""
        # Supprimer le message de commande
        try:
            await ctx.message.delete()
        except:
            pass
        
        if ctx.channel.id in self.tableau_messages:
            del self.tableau_messages[ctx.channel.id]
            await ctx.send("✅ Mise à jour du tableau arrêtée dans ce channel.", delete_after=10)
        else:
            await ctx.send("❌ Aucun tableau actif dans ce channel.", delete_after=10)
    
    @commands.command(name='TS')
    async def ts_command(self, ctx, personne: discord.Member = None):
        """Affiche le tableau de service par jour pour une personne"""
        # Supprimer le message de commande
        try:
            await ctx.message.delete()
        except:
            pass
        
        if personne is None:
            personne = ctx.author
        
        user_id = str(personne.id)
        
        if user_id not in self.historique or not self.historique[user_id]:
            await ctx.send(f"📭 {personne.mention} n'a pas encore de service enregistré.")
            return
        
        embed = discord.Embed(
            title=f"📅 SERVICE HEBDOMADAIRE - {personne.display_name}",
            color=discord.Color.green(),
            timestamp=self.get_datetime_now()
        )
        
        total_semaine_sec = 0
        items = sorted(self.historique[user_id].items(), key=lambda x: x[0])
        
        # Afficher les 7 derniers jours
        for date_str, temps_sec in items[-7:]:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d")
            jour = self.jours_semaine[date_obj.weekday()]
            duree_formatee = self.format_duree(temps_sec)
            
            embed.add_field(
                name=f"{jour} ({date_str})",
                value=f"**{duree_formatee}**",
                inline=False
            )
            total_semaine_sec += temps_sec
        
        total_formate = self.format_duree(total_semaine_sec)
        embed.set_footer(text=f"Total semaine: {total_formate}")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='mon_timer')
    async def mon_timer_command(self, ctx):
        """Montre votre timer en direct avec détails"""
        # Supprimer le message de commande
        try:
            await ctx.message.delete()
        except:
            pass
        
        user_id = str(ctx.author.id)
        
        if user_id not in self.en_service:
            await ctx.send(f"❌ {ctx.author.mention}, vous n'êtes pas en service !", delete_after=10)
            return
        
        service_data = self.en_service[user_id]
        session_start = service_data["session_start"]
        debut_global = service_data["debut"]
        
        temps_session_sec = (self.get_datetime_now() - session_start).seconds
        temps_historique = self.get_temps_cumule_du_jour(user_id)
        temps_total_sec = temps_historique + temps_session_sec
        
        embed = discord.Embed(
            title=f"⏱️ TIMER DE {ctx.author.display_name}",
            color=discord.Color.green(),
            timestamp=self.get_datetime_now()
        )
        
        embed.add_field(
            name="🕐 Session en cours",
            value=f"{self.format_duree_live(temps_session_sec)}",
            inline=False
        )
        
        embed.add_field(
            name="📊 Total aujourd'hui",
            value=f"{self.format_duree(temps_total_sec)}",
            inline=False
        )
        
        embed.add_field(
            name="⏰ Début session",
            value=f"{session_start.strftime('%H:%M:%S')}",
            inline=True
        )
        
        embed.add_field(
            name="📅 Premier début",
            value=f"{debut_global.strftime('%H:%M:%S')}",
            inline=True
        )
        
        embed.set_footer(text="Le tableau principal se met à jour chaque seconde !")
        
        await ctx.send(embed=embed, delete_after=30)
    
    @commands.command(name='TSG', aliases=['classement', 'top'])
    async def tsg_command(self, ctx):
        """Affiche le tableau de service global (7 derniers jours)"""
        # Supprimer le message de commande
        try:
            await ctx.message.delete()
        except:
            pass
        
        if not self.historique:
            await ctx.send("📭 Aucun service enregistré.")
            return
        
        embed = discord.Embed(
            title="🏆 CLASSEMENT HEBDOMADAIRE",
            color=discord.Color.gold(),
            timestamp=self.get_datetime_now()
        )
        
        classements = []
        for user_id, jours in self.historique.items():
            # Somme des 7 derniers jours
            dates_triees = sorted(jours.keys())
            derniers_7_jours = dates_triees[-7:] if len(dates_triees) >= 7 else dates_triees
            total_sec = sum(jours[date] for date in derniers_7_jours)
            
            if total_sec > 0:
                user = self.bot.get_user(int(user_id))
                if user:
                    duree_formatee = self.format_duree(total_sec)
                    classements.append((total_sec, user.display_name, duree_formatee))
        
        # Tri décroissant par secondes
        classements.sort(reverse=True)
        
        description = ""
        for i, (_, nom, duree) in enumerate(classements[:10], 1):
            emoji = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"**{i}.**"
            description += f"{emoji} **{nom}** - {duree}\n"
        
        embed.description = description or "*Aucune donnée*"
        embed.set_footer(text="Basé sur les 7 derniers jours")
        
        await ctx.send(embed=embed)
    
    @commands.command(name='mon_service')
    async def mon_service_command(self, ctx):
        """Affiche votre statut de service actuel"""
        # Supprimer le message de commande
        try:
            await ctx.message.delete()
        except:
            pass
        
        user_id = str(ctx.author.id)
        today = self.get_date_du_jour()
        
        if user_id in self.en_service:
            service_data = self.en_service[user_id]
            session_start = service_data["session_start"]
            debut_global = service_data["debut"]
            
            temps_session_sec = (self.get_datetime_now() - session_start).seconds
            temps_historique = self.get_temps_cumule_du_jour(user_id)
            temps_total_sec = temps_historique + temps_session_sec
            
            temps_session = self.format_duree(temps_session_sec)
            temps_total = self.format_duree(temps_total_sec)
            
            embed = discord.Embed(
                title=f"✅ {ctx.author.display_name} - EN SERVICE",
                color=discord.Color.green(),
                timestamp=self.get_datetime_now()
            )
            
            embed.add_field(name="⏱️ Session en cours", value=temps_session, inline=True)
            embed.add_field(name="📊 Total aujourd'hui", value=temps_total, inline=True)
            embed.add_field(name="🕐 Début session", value=session_start.strftime('%H:%M:%S'), inline=True)
            embed.add_field(name="📅 Premier début", value=debut_global.strftime('%H:%M:%S'), inline=True)
            
            await ctx.send(embed=embed, delete_after=30)
            
        elif user_id in self.services_termines and self.services_termines[user_id].get('date') == today:
            data = self.services_termines[user_id]
            
            embed = discord.Embed(
                title=f"🔴 {ctx.author.display_name} - SERVICE TERMINÉ",
                color=discord.Color.red(),
                timestamp=self.get_datetime_now()
            )
            
            embed.add_field(name="⏱️ Dernière session", value=data['temps_session'], inline=True)
            embed.add_field(name="📊 Total aujourd'hui", value=data['temps_total'], inline=True)
            embed.add_field(name="🕐 Début", value=data['heure_debut'], inline=True)
            embed.add_field(name="⏰ Fin", value=data['heure_fin'], inline=True)
            
            await ctx.send(embed=embed, delete_after=30)
            
        else:
            # Vérifier le temps déjà fait aujourd'hui
            temps_deja_fait = self.get_temps_cumule_du_jour(user_id)
            
            if temps_deja_fait > 0:
                temps_formate = self.format_duree(temps_deja_fait)
                await ctx.send(
                    f"📊 {ctx.author.mention}, vous n'êtes pas actuellement en service.\n"
                    f"**Temps fait aujourd'hui:** {temps_formate}",
                    delete_after=10
                )
            else:
                await ctx.send(
                    f"📭 {ctx.author.mention}, vous n'êtes pas actuellement en service.",
                    delete_after=10
                )
    
    @commands.command(name='aujourdhui')
    async def aujourdhui_command(self, ctx):
        """Affiche les statistiques du jour"""
        # Supprimer le message de commande
        try:
            await ctx.message.delete()
        except:
            pass
        
        today = self.get_date_du_jour()
        
        embed = discord.Embed(
            title=f"📊 STATISTIQUES DU JOUR - {today}",
            color=discord.Color.blue(),
            timestamp=self.get_datetime_now()
        )
        
        # Personnes en service
        en_service_list = []
        for uid in self.en_service:
            user = self.bot.get_user(int(uid))
            if user:
                en_service_list.append(f"• {user.display_name}")
        
        # Personnes ayant terminé
        termines_list = []
        for uid, data in self.services_termines.items():
            if data.get('date') == today:
                user = self.bot.get_user(int(uid))
                if user:
                    termines_list.append(f"• {user.display_name} - {data['temps_total']}")
        
        # Calculer les totaux
        total_today_sec = 0
        for user_id, jours in self.historique.items():
            if today in jours:
                total_today_sec += jours[today]
        
        total_formate = self.format_duree(total_today_sec)
        
        embed.add_field(
            name="🟢 En service",
            value="\n".join(en_service_list) if en_service_list else "*Aucune personne*",
            inline=True
        )
        
        embed.add_field(
            name="🔴 Terminés",
            value="\n".join(termines_list) if termines_list else "*Aucune personne*",
            inline=True
        )
        
        embed.add_field(
            name="📈 Résumé",
            value=f"**Total personnes:** {len(en_service_list) + len(termines_list)}\n"
                  f"**En service:** {len(en_service_list)}\n"
                  f"**Terminés:** {len(termines_list)}\n"
                  f"**Total temps:** {total_formate}",
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    @commands.command(name='sauvegarder')
    @commands.has_permissions(administrator=True)
    async def sauvegarder_command(self, ctx):
        """Force la sauvegarde des données"""
        # Supprimer le message de commande
        try:
            await ctx.message.delete()
        except:
            pass
        
        self.sauvegarder_donnees()
        await ctx.send("✅ Données service sauvegardées !", delete_after=5)
    
    @commands.command(name='reset_service')
    @commands.has_permissions(administrator=True)
    async def reset_service_command(self, ctx):
        """Réinitialise tous les services en cours (admin only)"""
        # Supprimer le message de commande
        try:
            await ctx.message.delete()
        except:
            pass
        
        self.en_service = {}
        self.services_termines = {}
        self.sauvegarder_donnees()
        await ctx.send("✅ Tous les services en cours ont été réinitialisés !", delete_after=5)
    
    @commands.command(name='reset_quotidien')
    @commands.has_permissions(administrator=True)
    async def reset_quotidien_command(self, ctx):
        """Réinitialise les données du jour (admin only)"""
        # Supprimer le message de commande
        try:
            await ctx.message.delete()
        except:
            pass
        
        self.services_termines = {}
        self.sauvegarder_donnees()
        await ctx.send("✅ Données quotidiennes réinitialisées !", delete_after=5)
    
    # ========== ÉVÉNEMENTS ==========
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Recharge la vue persistante au redémarrage"""
        print("✅ Module Service prêt | Tableau en direct activé")
    
    def cog_unload(self):
        """Arrête les tâches quand le cog est déchargé"""
        self.update_tableau.cancel()
        self.reset_quotidien.cancel()

async def setup(bot):
    """Fonction d'installation du cog"""
    await bot.add_cog(Service(bot))
