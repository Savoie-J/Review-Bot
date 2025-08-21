import os
import json
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("token")

SETTINGS_FILE = "settings.json"

if not os.path.exists(SETTINGS_FILE):
    with open(SETTINGS_FILE, "w") as f:
        json.dump({}, f)

def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    try:
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)


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
        embed = discord.Embed(
            title=f"Testimonial for {self.target_user.display_name} <a:kv7_wave:1285921863901646849>",
            description=self.review_input.value,
            color=discord.Color.random(),
            timestamp=interaction.created_at
        )
        embed.set_author(name=f"New Review!", icon_url=interaction.user.display_avatar.url)
        embed.set_thumbnail(url=self.target_user.display_avatar.url)
        embed.add_field(name="Reviewer", value=f"{interaction.user.mention} ({interaction.user.display_name})", inline=True)
        embed.add_field(name="Reviewed", value=f"{self.target_user.mention} ({self.target_user.display_name})", inline=True)
        embed.set_footer(text=f"Submitted")

        channel = interaction.guild.get_channel(self.testimonial_channel_id)
        if channel:
            await channel.send(embed=embed)
            
            role_message = ""
            if self.reward_role_id:
                reward_role = interaction.guild.get_role(self.reward_role_id)
                if reward_role and reward_role not in interaction.user.roles:
                    try:
                        await interaction.user.add_roles(reward_role, reason="Left a review")
                        role_message = f" You've been awarded the {reward_role.name} role!"
                    except discord.Forbidden:
                        role_message = f" (Could not assign {reward_role.name} role - insufficient permissions)"
                    except discord.HTTPException as e:
                        role_message = f" (Error assigning role: {str(e)})"
                elif reward_role and reward_role in interaction.user.roles:
                    role_message = f" (You already have the {reward_role.name} role)"
            
            await interaction.response.send_message(f"✅ Your review has been posted!{role_message}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Testimonial channel not found.", ephemeral=True)

class UserSelectView(discord.ui.View):
    def __init__(self, testimonial_channel_id: int, guild: discord.Guild, role_id: int = None, reward_role_id: int = None):
        super().__init__(timeout=60)
        self.testimonial_channel_id = testimonial_channel_id
        self.guild = guild
        self.role_id = role_id
        self.reward_role_id = reward_role_id

        if role_id:
            role = guild.get_role(role_id)
            members = [m for m in role.members if not m.bot] if role else []
        else:
            members = [m for m in guild.members if not m.bot]

        if members:
            options = [discord.SelectOption(label=m.display_name, value=str(m.id)) for m in members]
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

    async def select_user(self, interaction: discord.Interaction):
        user_id = int(interaction.data['values'][0])
        target_user = self.guild.get_member(user_id)
        if not target_user:
            await interaction.response.send_message("❌ User not found.", ephemeral=True)
            return
        
        await interaction.response.send_modal(ReviewModal(target_user, self.testimonial_channel_id, self.reward_role_id))

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
                    print(f"[setup_hook] Reattached persistent view to message {review_message_id} in guild {guild_id_str}")
                except Exception as e:
                    print(f"[setup_hook] Failed to reattach view for guild {guild_id_str}: {e}")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")
        await self.tree.sync()

bot = ReviewBot()

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
    settings = load_settings()
    guild_id = str(interaction.guild.id)

    if action.value == "set_review_channel":
        if channel is None:
            await interaction.response.send_message("❌ Please provide a channel.", ephemeral=True)
            return

        if guild_id not in settings:
            settings[guild_id] = {}

        settings[guild_id]["review_channel"] = channel.id
        save_settings(settings)

        testimonial_id = settings[guild_id].get("testimonial_channel")
        role_id = settings[guild_id].get("reviewable_role")
        reward_role_id = settings[guild_id].get("reward_role")

        if testimonial_id:
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
        if guild_id not in settings:
            settings[guild_id] = {}
        settings[guild_id]["testimonial_channel"] = channel.id
        save_settings(settings)
        await interaction.response.send_message(f"✅ Testimonial channel set to {channel.mention}.", ephemeral=True)

    elif action.value == "set_reviewable_role":
        if role is None:
            await interaction.response.send_message("❌ Please provide a role.", ephemeral=True)
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

        msg = ""
        msg += f"💬 Review channel: {interaction.guild.get_channel(current_review).mention if current_review else 'Not set'}\n"
        msg += f"📝 Testimonial channel: {interaction.guild.get_channel(current_testimonial).mention if current_testimonial else 'Not set'}\n"
        msg += f"👤 Staff role: {interaction.guild.get_role(current_role).mention if current_role else 'Not set'}\n"
        msg += f"🎁 Reward role: {interaction.guild.get_role(current_reward_role).mention if current_reward_role else 'Not set'}\n"

        await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="generate", description="Post the review embed in the configured review channel")
@discord.app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def generate_review_post(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    settings = load_settings()
    role_id = settings.get(guild_id, {}).get("reviewable_role")
    reward_role_id = settings.get(guild_id, {}).get("reward_role")

    if (guild_id not in settings or "review_channel" not in settings[guild_id] or "testimonial_channel" not in settings[guild_id]):
        await interaction.response.send_message("❌ You must set both the review and testimonial channels first using `/settings`.", ephemeral=True)
        return

    review_channel_id = settings[guild_id]["review_channel"]
    testimonial_channel_id = settings[guild_id]["testimonial_channel"]
    review_channel = interaction.guild.get_channel(review_channel_id)

    if review_channel is None:
        await interaction.response.send_message("❌ Review channel not found. Please reconfigure `/settings`.", ephemeral=True)
        return

    embed = discord.Embed(title="💬 Leave a Review", description="Click the button below to review a staff member of this server.", color=discord.Color.blurple())
    view = ReviewButtonView(testimonial_channel_id, role_id, reward_role_id)
    message = await review_channel.send(embed=embed, view=view)

    settings[guild_id]["review_message_id"] = message.id
    save_settings(settings)

    bot.add_view(ReviewButtonView(testimonial_channel_id, role_id, reward_role_id), message_id=message.id)

    await interaction.response.send_message(f"✅ Review embed posted in {review_channel.mention}", ephemeral=True)

bot.run(TOKEN)