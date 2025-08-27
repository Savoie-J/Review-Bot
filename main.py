import os
import json
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
import uuid
from datetime import datetime
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()
TOKEN = os.getenv("token")

if not TOKEN:
    raise ValueError("Discord bot token not found. Please check your .env file.")

SETTINGS_FILE = "settings.json"
BACKUP_FILE = "review_backup.json"

MAX_REVIEW_LENGTH = 1000
SUSPICIOUS_PATTERNS = [
    r'@everyone',
    r'@here', 
    r'discord\.gg/',
    r'https?://bit\.ly/',
    r'https?://tinyurl\.com/',
    r'<@&\d+>',  # Mass role mentions
]

def sanitize_content(content: str) -> tuple[str, bool]:
    """
    Sanitize review content and check for suspicious patterns.
    Returns (sanitized_content, is_suspicious)
    """
    # Remove potential markdown abuse
    sanitized = content.replace('`', '').replace('*', '').replace('_', '').replace('~', '')
    
    # Check for suspicious patterns
    is_suspicious = False
    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, content, re.IGNORECASE):
            is_suspicious = True
            break
    
    # Check for excessive mentions
    mention_count = content.count('<@') + content.count('<#')
    if mention_count > 3:
        is_suspicious = True
    
    return sanitized[:MAX_REVIEW_LENGTH], is_suspicious

if not os.path.exists(SETTINGS_FILE):
    with open(SETTINGS_FILE, "w") as f:
        json.dump({}, f)

if not os.path.exists(BACKUP_FILE):
    with open(BACKUP_FILE, "w") as f:
        json.dump({}, f)

def load_settings():
    """Load settings with error handling and validation"""
    try:
        if not os.path.exists(SETTINGS_FILE):
            return {}
        with open(SETTINGS_FILE, "r", encoding='utf-8') as f:
            settings = json.load(f)
            # Validate settings structure
            if not isinstance(settings, dict):
                logger.warning("Invalid settings format, resetting to empty dict")
                return {}
            return settings
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load settings: {e}")
        return {}

def save_settings(settings):
    """Save settings with error handling"""
    try:
        with open(SETTINGS_FILE, "w", encoding='utf-8') as f:
            json.dump(settings, f, indent=4)
    except (IOError, TypeError) as e:
        logger.error(f"Failed to save settings: {e}")
        raise

def load_backup():
    """Load backup with error handling and validation"""
    try:
        if not os.path.exists(BACKUP_FILE):
            return {}
        with open(BACKUP_FILE, "r", encoding='utf-8') as f:
            backup = json.load(f)
            # Validate backup structure
            if not isinstance(backup, dict):
                logger.warning("Invalid backup format, resetting to empty dict")
                return {}
            return backup
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Failed to load backup: {e}")
        return {}

def save_backup(backup):
    """Save backup with error handling"""
    try:
        with open(BACKUP_FILE, "w", encoding='utf-8') as f:
            json.dump(backup, f, indent=4)
    except (IOError, TypeError) as e:
        logger.error(f"Failed to save backup: {e}")
        # Don't raise here - we don't want to break the review process

def backup_review(guild_id: int, reviewer_id: int, reviewed_id: int, review_content: str, timestamp: datetime):
    """Save a review to the backup file with a unique ID"""
    try:
        backup = load_backup()
        guild_id_str = str(guild_id)
        
        if guild_id_str not in backup:
            backup[guild_id_str] = {}
        
        # Generate unique ID
        review_id = str(uuid.uuid4())
        
        # Sanitize content for backup
        sanitized_content, _ = sanitize_content(review_content)
        
        # Store review data with validation
        backup[guild_id_str][review_id] = {
            "reviewer_id": int(reviewer_id),
            "reviewed_id": int(reviewed_id), 
            "content": sanitized_content,
            "timestamp": timestamp.isoformat(),
            "created_at": datetime.now().isoformat()
        }
        
        save_backup(backup)
        return review_id
    except Exception as e:
        logger.error(f"Failed to backup review: {e}")
        return None

class ReviewModal(discord.ui.Modal, title="Leave a Review"):
    def __init__(self, target_user: discord.User, testimonial_channel_id: int, reward_role_id: int = None):
        super().__init__()
        self.target_user = target_user
        self.testimonial_channel_id = testimonial_channel_id
        self.reward_role_id = reward_role_id

        self.review_input = discord.ui.TextInput(
            label="Your Review",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True
        )
        self.add_item(self.review_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            sanitized_content, is_suspicious = sanitize_content(self.review_input.value)
            
            if not sanitized_content.strip():
                await interaction.response.send_message("❌ Review cannot be empty.", ephemeral=True)
                return
            
            if len(sanitized_content) < 10:
                await interaction.response.send_message("❌ Review must be at least 10 characters long.", ephemeral=True)
                return
            
            if is_suspicious:
                logger.warning(f"Suspicious review content from user {interaction.user.id}: {sanitized_content[:100]}...")
            
            if not self.target_user or not interaction.guild.get_member(self.target_user.id):
                await interaction.response.send_message("❌ The user you're trying to review is no longer available.", ephemeral=True)
                return
            
            review_id = backup_review(
                guild_id=interaction.guild.id,
                reviewer_id=interaction.user.id,
                reviewed_id=self.target_user.id,
                review_content=sanitized_content,
                timestamp=interaction.created_at
            )
            
            if review_id:
                logger.info(f"Review backed up with ID: {review_id}")
            else:
                logger.error("Failed to backup review, but continuing with posting")

            embed = discord.Embed(
                title=f"Testimonial for {self.target_user.display_name} <a:kv7_wave:1285921863901646849>",
                description=sanitized_content,
                color=discord.Color.random(),
                timestamp=interaction.created_at
            )
            embed.set_author(name=f"New Review!", icon_url=interaction.user.display_avatar.url)
            embed.set_thumbnail(url=self.target_user.display_avatar.url)
            embed.add_field(
                name="Reviewer",
                value=f"{interaction.user.mention} (`{interaction.user.name}`)",
                inline=True
            )
            embed.add_field(
                name="Reviewed",
                value=f"{self.target_user.mention} (`{self.target_user.name}`)",
                inline=True
            )
            
            if review_id:
                embed.set_footer(text=f"ID: {review_id} • Submitted")
            else:
                embed.set_footer(text="Submitted")

            channel = interaction.guild.get_channel(self.testimonial_channel_id)
            if not channel:
                await interaction.response.send_message("❌ Testimonial channel not found. Please contact an administrator.", ephemeral=True)
                return
                
            if not channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.response.send_message("❌ I don't have permission to send messages in the testimonial channel.", ephemeral=True)
                return

            await channel.send(embed=embed)
            
            role_message = ""
            if self.reward_role_id:
                try:
                    reward_role = interaction.guild.get_role(self.reward_role_id)
                    if not reward_role:
                        role_message = " (Reward role no longer exists)"
                    elif reward_role in interaction.user.roles:
                        role_message = f" (You already have the {reward_role.name} role)"
                    else:
                        await interaction.user.add_roles(reward_role, reason="Left a review")
                        role_message = f" You've been awarded the {reward_role.name} role!"
                except discord.Forbidden:
                    role_message = f" (Could not assign reward role - insufficient permissions)"
                except discord.HTTPException as e:
                    logger.error(f"Error assigning role: {e}")
                    role_message = f" (Error assigning role)"
            
            await interaction.response.send_message(f"✅ Your review has been posted!{role_message}", ephemeral=True)
            
        except discord.InteractionResponded:
            pass
        except discord.Forbidden as e:
            logger.error(f"Permission error in review submission: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ I don't have the necessary permissions to complete this action. Please contact an administrator.", ephemeral=True)
            except:
                pass
        except discord.HTTPException as e:
            logger.error(f"Discord API error in review submission: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ Discord API error: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}", ephemeral=True)
            except:
                pass
        except Exception as e:
            logger.error(f"Unexpected error in review submission: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ An unexpected error occurred: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}", ephemeral=True)
            except:
                pass

class UserSelectView(discord.ui.View):
    def __init__(self, testimonial_channel_id: int, guild: discord.Guild, role_id: int = None, reward_role_id: int = None):
        super().__init__(timeout=60)
        self.testimonial_channel_id = testimonial_channel_id
        self.guild = guild
        self.role_id = role_id
        self.reward_role_id = reward_role_id

        try:
            # Get members to review with better filtering
            if role_id:
                role = guild.get_role(role_id)
                members = [m for m in role.members if not m.bot and m.id != guild.me.id] if role else []
            else:
                # Limit to members with certain permissions to avoid spam targets
                members = [m for m in guild.members if not m.bot and m.id != guild.me.id and (
                    m.guild_permissions.kick_members or 
                    m.guild_permissions.manage_messages or 
                    m.guild_permissions.manage_roles
                )]

            # Limit the number of options to prevent Discord API limits
            members = members[:25]  # Discord select menu limit

            if members:
                options = [
                    discord.SelectOption(
                        label=m.display_name[:100],  # Prevent label overflow
                        value=str(m.id),
                        description=f"@{m.name}"[:100] if m.name != m.display_name else None
                    ) for m in members
                ]
                select = discord.ui.Select(
                    placeholder="Select a staff member to review",
                    min_values=1,
                    max_values=1,
                    options=options,
                    custom_id="user_select_filtered"
                )
                select.callback = self.select_user
                self.add_item(select)
            else:
                select = discord.ui.Select(
                    placeholder="No staff available to review",
                    min_values=1,
                    max_values=1,
                    options=[discord.SelectOption(label="No staff available", value="none", default=True)],
                    disabled=True
                )
                self.add_item(select)
        except Exception as e:
            logger.error(f"Error initializing UserSelectView: {e}")
            # Add fallback disabled select
            select = discord.ui.Select(
                placeholder="Error loading staff list",
                options=[discord.SelectOption(label="Error occurred", value="error")],
                disabled=True
            )
            self.add_item(select)

    async def select_user(self, interaction: discord.Interaction):
        try:
            user_id = int(interaction.data['values'][0])
            target_user = self.guild.get_member(user_id)
            
            if not target_user:
                await interaction.response.send_message("❌ User not found or no longer in the server.", ephemeral=True)
                return
            
            # Prevent self-reviews
            if target_user.id == interaction.user.id:
                await interaction.response.send_message("❌ You cannot review yourself.", ephemeral=True)
                return
                
            await interaction.response.send_modal(ReviewModal(target_user, self.testimonial_channel_id, self.reward_role_id))
            
        except (ValueError, KeyError) as e:
            logger.error(f"Data error in select_user: {e}")
            await interaction.response.send_message(f"❌ Data validation error: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}", ephemeral=True)
        except discord.NotFound as e:
            logger.error(f"Discord object not found in select_user: {e}")
            await interaction.response.send_message("❌ The selected user or channel could not be found. Please try again.", ephemeral=True)
        except discord.Forbidden as e:
            logger.error(f"Permission error in select_user: {e}")
            await interaction.response.send_message("❌ I don't have permission to perform this action. Please contact an administrator.", ephemeral=True)
        except Exception as e:
            logger.error(f"Unexpected error in select_user: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Unexpected error: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}", ephemeral=True)

class ReviewButtonView(discord.ui.View):
    def __init__(self, testimonial_channel_id: int, role_id: int | None = None, reward_role_id: int | None = None):
        super().__init__(timeout=None)
        self.testimonial_channel_id = testimonial_channel_id
        self.role_id = role_id
        self.reward_role_id = reward_role_id

    @discord.ui.button(
        label="Leave a Review",
        style=discord.ButtonStyle.blurple,
        custom_id="review_button_persistent"
    )
    async def review_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            # Check if user has been muted/restricted.
            if hasattr(interaction.user, 'timed_out') and interaction.user.timed_out:
                await interaction.response.send_message("❌ You cannot leave reviews while timed out.", ephemeral=True)
                return
            
            await interaction.response.send_message(
                "Select the user you wish to review:",
                view=UserSelectView(
                    testimonial_channel_id=self.testimonial_channel_id,
                    guild=interaction.guild,
                    role_id=self.role_id,
                    reward_role_id=self.reward_role_id
                ),
                ephemeral=True
            )
        except discord.Forbidden as e:
            logger.error(f"Permission error in review_button: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("❌ I don't have the necessary permissions. Please contact an administrator.", ephemeral=True)
            except:
                pass
        except discord.HTTPException as e:
            logger.error(f"Discord API error in review_button: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ Discord API error: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}", ephemeral=True)
            except:
                pass
        except Exception as e:
            logger.error(f"Unexpected error in review_button: {e}")
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message(f"❌ Unexpected error: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}", ephemeral=True)
            except:
                pass

class ReviewBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = False
        intents.members = True
        super().__init__(command_prefix=None, intents=intents)

    async def setup_hook(self):
        settings = load_settings()
        for guild_id_str, data in settings.items():
            testimonial_channel_id = data.get("testimonial_channel")
            role_id = data.get("reviewable_role")
            reward_role_id = data.get("reward_role")
            review_message_id = data.get("review_message_id")

            if testimonial_channel_id and review_message_id:
                try:
                    view = ReviewButtonView(testimonial_channel_id, role_id, reward_role_id)
                    self.add_view(view, message_id=review_message_id)
                    logger.info(f"Reattached persistent view to message {review_message_id} in guild {guild_id_str}")
                except Exception as e:
                    logger.error(f"Failed to reattach view for guild {guild_id_str}: {e}")

    async def on_ready(self):
        logger.info(f"✅ Logged in as {self.user} (ID: {self.user.id})")
        await self.tree.sync()

bot = ReviewBot()

@bot.tree.command(name="backup_info", description="Show backup statistics")
@discord.app_commands.default_permissions(administrator=True)
async def backup_info(interaction: discord.Interaction):
    """Show information about backed up reviews"""
    try:
        backup = load_backup()
        guild_id_str = str(interaction.guild.id)
        
        if guild_id_str not in backup or not backup[guild_id_str]:
            await interaction.response.send_message("📦 No reviews backed up for this server.", ephemeral=True)
            return
        
        review_count = len(backup[guild_id_str])
        
        # Get some basic stats with error handling
        reviewers = set()
        reviewed = set()
        valid_reviews = 0
        
        for review_id, review_data in backup[guild_id_str].items():
            try:
                if isinstance(review_data, dict) and "reviewer_id" in review_data and "reviewed_id" in review_data:
                    reviewers.add(review_data["reviewer_id"])
                    reviewed.add(review_data["reviewed_id"])
                    valid_reviews += 1
            except Exception as e:
                logger.warning(f"Invalid review data for ID {review_id}: {e}")
        
        embed = discord.Embed(
            title="📦 Review Backup Information",
            color=discord.Color.blue(),
            timestamp=interaction.created_at
        )
        embed.add_field(name="Total Reviews Backed Up", value=str(valid_reviews), inline=True)
        embed.add_field(name="Unique Reviewers", value=str(len(reviewers)), inline=True)
        embed.add_field(name="Unique Staff Reviewed", value=str(len(reviewed)), inline=True)
        embed.set_footer(text="Backup system active")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
        
    except FileNotFoundError as e:
        logger.error(f"File not found in backup_info command: {e}")
        await interaction.response.send_message("❌ Backup file not found. No reviews have been backed up yet.", ephemeral=True)
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error in backup_info command: {e}")
        await interaction.response.send_message("❌ Backup file is corrupted. Please contact an administrator.", ephemeral=True)
    except Exception as e:
        logger.error(f"Unexpected error in backup_info command: {e}")
        await interaction.response.send_message(f"❌ Unexpected error while retrieving backup info: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}", ephemeral=True)

@bot.tree.command(name="settings", description="Manage settings")
@discord.app_commands.default_permissions(administrator=True)
@app_commands.describe(action="Choose an action", channel="The channel to assign (if applicable)", role="The role to assign")
@app_commands.choices(action=[
    app_commands.Choice(name="Set Review Channel", value="set_review_channel"),
    app_commands.Choice(name="Set Testimonial Channel", value="set_testimonial_channel"),
    app_commands.Choice(name="Set Staff Role", value="set_reviewable_role"),
    app_commands.Choice(name="Set Reward Role", value="set_reward_role"),
    app_commands.Choice(name="Clear Settings", value="clear"),
    app_commands.Choice(name="List Settings", value="list")
])
async def settings_command(interaction: discord.Interaction, action: app_commands.Choice[str], channel: discord.TextChannel = None, role: discord.Role = None):
    try:
        settings = load_settings()
        guild_id = str(interaction.guild.id)

        if action.value == "set_review_channel":
            if channel is None:
                await interaction.response.send_message("❌ Please provide a channel.", ephemeral=True)
                return

            # Validate bot permissions in the channel
            if not channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.response.send_message("❌ I don't have permission to send messages in that channel.", ephemeral=True)
                return

            if guild_id not in settings:
                settings[guild_id] = {}

            settings[guild_id]["review_channel"] = channel.id
            save_settings(settings)

            testimonial_id = settings[guild_id].get("testimonial_channel")
            role_id = settings[guild_id].get("reviewable_role")
            reward_role_id = settings[guild_id].get("reward_role")

            if testimonial_id:
                # Validate testimonial channel still exists
                testimonial_channel = interaction.guild.get_channel(testimonial_id)
                if not testimonial_channel:
                    await interaction.response.send_message(f"⚠️ Review channel set to {channel.mention}, but testimonial channel is invalid. Please reconfigure.", ephemeral=True)
                    return

                embed = discord.Embed(title="💬 Leave a Review", description="Click the button below to submit your testimonial.", color=discord.Color.blurple())
                view = ReviewButtonView(testimonial_id, role_id, reward_role_id)
                message = await channel.send(embed=embed, view=view)
                settings[guild_id]["review_message_id"] = message.id
                save_settings(settings)

                bot.add_view(ReviewButtonView(testimonial_id, role_id, reward_role_id), message_id=message.id)

                await interaction.response.send_message(f"✅ Review channel set to {channel.mention} and embed posted.", ephemeral=True)
            else:
                await interaction.response.send_message(f"✅ Review channel set to {channel.mention}, but testimonial channel not set yet.", ephemeral=True)

        elif action.value == "set_testimonial_channel":
            if channel is None:
                await interaction.response.send_message("❌ Please provide a channel.", ephemeral=True)
                return
                
            # Validate bot permissions in the channel
            if not channel.permissions_for(interaction.guild.me).send_messages:
                await interaction.response.send_message("❌ I don't have permission to send messages in that channel.", ephemeral=True)
                return
                
            if guild_id not in settings:
                settings[guild_id] = {}
            settings[guild_id]["testimonial_channel"] = channel.id
            save_settings(settings)
            await interaction.response.send_message(f"✅ Testimonial channel set to {channel.mention}.", ephemeral=True)

        elif action.value == "set_reviewable_role":
            if role is None:
                await interaction.response.send_message("❌ Please provide a role.", ephemeral=True)
                return
                
            # Validate role isn't @everyone or managed by bot
            if role.id == interaction.guild.id:  # @everyone role
                await interaction.response.send_message("❌ Cannot use @everyone as reviewable role.", ephemeral=True)
                return
                
            if role.managed:
                await interaction.response.send_message("❌ Cannot use bot-managed roles.", ephemeral=True)
                return
                
            if guild_id not in settings:
                settings[guild_id] = {}
            settings[guild_id]["reviewable_role"] = role.id
            save_settings(settings)
            await interaction.response.send_message(f"✅ Reviewable role set to {role.name}.", ephemeral=True)

        elif action.value == "set_reward_role":
            if role is None:
                await interaction.response.send_message("❌ Please provide a role.", ephemeral=True)
                return
                
            # Validate role permissions and hierarchy
            if role.id == interaction.guild.id:  # @everyone role
                await interaction.response.send_message("❌ Cannot use @everyone as reward role.", ephemeral=True)
                return
                
            if role.managed:
                await interaction.response.send_message("❌ Cannot use bot-managed roles.", ephemeral=True)
                return
                
            if role >= interaction.guild.me.top_role:
                await interaction.response.send_message("❌ Role is higher than my highest role. Please move my role higher or choose a lower role.", ephemeral=True)
                return
                
            if guild_id not in settings:
                settings[guild_id] = {}
            settings[guild_id]["reward_role"] = role.id
            save_settings(settings)
            await interaction.response.send_message(f"✅ Reward role set to {role.name}. Users will receive this role after leaving a review.", ephemeral=True)

        elif action.value == "clear":
            settings.pop(guild_id, None)
            save_settings(settings)
            await interaction.response.send_message("✅ Settings cleared.", ephemeral=True)

        elif action.value == "list":
            current_review = settings.get(guild_id, {}).get("review_channel")
            current_testimonial = settings.get(guild_id, {}).get("testimonial_channel")
            current_role = settings.get(guild_id, {}).get("reviewable_role")
            current_reward_role = settings.get(guild_id, {}).get("reward_role")

            embed = discord.Embed(title="⚙️ Current Settings", color=discord.Color.blue())
            
            # Validate channels and roles still exist
            review_channel = interaction.guild.get_channel(current_review) if current_review else None
            testimonial_channel = interaction.guild.get_channel(current_testimonial) if current_testimonial else None
            reviewable_role = interaction.guild.get_role(current_role) if current_role else None
            reward_role = interaction.guild.get_role(current_reward_role) if current_reward_role else None
            
            embed.add_field(
                name="💬 Review Channel", 
                value=review_channel.mention if review_channel else "Not set or invalid", 
                inline=False
            )
            embed.add_field(
                name="📝 Testimonial Channel", 
                value=testimonial_channel.mention if testimonial_channel else "Not set or invalid", 
                inline=False
            )
            embed.add_field(
                name="👤 Staff Role", 
                value=reviewable_role.mention if reviewable_role else "Not set or invalid", 
                inline=False
            )
            embed.add_field(
                name="🎁 Reward Role", 
                value=reward_role.mention if reward_role else "Not set or invalid", 
                inline=False
            )

            await interaction.response.send_message(embed=embed, ephemeral=True)
            
    except FileNotFoundError as e:
        logger.error(f"Settings file not found: {e}")
        await interaction.response.send_message("❌ Settings file not found. Please try setting up the bot again.", ephemeral=True)
    except json.JSONDecodeError as e:
        logger.error(f"Settings file corrupted: {e}")
        await interaction.response.send_message("❌ Settings file is corrupted. Please clear settings and reconfigure.", ephemeral=True)
    except discord.Forbidden as e:
        logger.error(f"Permission error in settings command: {e}")
        await interaction.response.send_message("❌ I don't have permission to perform this action. Please check my permissions.", ephemeral=True)
    except discord.HTTPException as e:
        logger.error(f"Discord API error in settings command: {e}")
        await interaction.response.send_message(f"❌ Discord API error: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}", ephemeral=True)
    except Exception as e:
        logger.error(f"Unexpected error in settings command: {e}")
        await interaction.response.send_message(f"❌ Unexpected error in settings: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}", ephemeral=True)

@bot.tree.command(name="generate", description="Post the review embed in the configured review channel")
@discord.app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def generate_review_post(interaction: discord.Interaction):
    try:
        guild_id = str(interaction.guild.id)
        settings = load_settings()
        
        if (guild_id not in settings or "review_channel" not in settings[guild_id] or "testimonial_channel" not in settings[guild_id]):
            await interaction.response.send_message("❌ You must set both the review and testimonial channels first using `/settings`.", ephemeral=True)
            return

        review_channel_id = settings[guild_id]["review_channel"]
        testimonial_channel_id = settings[guild_id]["testimonial_channel"]
        role_id = settings.get(guild_id, {}).get("reviewable_role")
        reward_role_id = settings.get(guild_id, {}).get("reward_role")
        
        # Validate channels exist and bot has permissions
        review_channel = interaction.guild.get_channel(review_channel_id)
        testimonial_channel = interaction.guild.get_channel(testimonial_channel_id)

        if review_channel is None:
            await interaction.response.send_message("❌ Review channel not found. Please reconfigure using `/settings`.", ephemeral=True)
            return
            
        if testimonial_channel is None:
            await interaction.response.send_message("❌ Testimonial channel not found. Please reconfigure using `/settings`.", ephemeral=True)
            return

        if not review_channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.response.send_message("❌ I don't have permission to send messages in the review channel.", ephemeral=True)
            return
            
        if not testimonial_channel.permissions_for(interaction.guild.me).send_messages:
            await interaction.response.send_message("❌ I don't have permission to send messages in the testimonial channel.", ephemeral=True)
            return

        embed = discord.Embed(title="💬 Leave a Review", description="Click the button below to review a staff member of this server.", color=discord.Color.blurple())
        view = ReviewButtonView(testimonial_channel_id, role_id, reward_role_id)
        
        message = await review_channel.send(embed=embed, view=view)

        settings[guild_id]["review_message_id"] = message.id
        save_settings(settings)

        bot.add_view(ReviewButtonView(testimonial_channel_id, role_id, reward_role_id), message_id=message.id)

        await interaction.response.send_message(f"✅ Review embed posted in {review_channel.mention}", ephemeral=True)
        
    except discord.Forbidden as e:
        logger.error(f"Permission error in generate command: {e}")
        await interaction.response.send_message("❌ I don't have permission to send messages in the review channel.", ephemeral=True)
    except discord.NotFound as e:
        logger.error(f"Channel not found in generate command: {e}")
        await interaction.response.send_message("❌ One of the configured channels no longer exists. Please reconfigure using `/settings`.", ephemeral=True)
    except discord.HTTPException as e:
        logger.error(f"Discord API error in generate command: {e}")
        await interaction.response.send_message(f"❌ Discord API error: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}", ephemeral=True)
    except Exception as e:
        logger.error(f"Unexpected error in generate command: {e}")
        await interaction.response.send_message(f"❌ Unexpected error while generating review post: {str(e)[:100]}{'...' if len(str(e)) > 100 else ''}", ephemeral=True)

bot.run(TOKEN)