import os
import json
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("token")

SETTINGS_FILE = "settings.json"

# Ensure settings file exists
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
    def __init__(self, target_user: discord.User, testimonial_channel_id: int):
        super().__init__()
        self.target_user = target_user
        self.testimonial_channel_id = testimonial_channel_id

        self.review_input = discord.ui.TextInput(
            label="Your Review",
            style=discord.TextStyle.paragraph,
            max_length=1000,
            required=True
        )
        self.add_item(self.review_input)

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"⭐ Testimonial for {self.target_user.display_name} ⭐",
            description=f"{self.target_user.mention}\n\n{self.review_input.value}",
            color=discord.Color.random()
        )
        embed.set_footer(text=f"Review by {interaction.user.display_name}")

        channel = interaction.guild.get_channel(self.testimonial_channel_id)
        if channel:
            await channel.send(embed=embed)
            await interaction.response.send_message("✅ Your review has been posted!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Testimonial channel not found.", ephemeral=True)


class UserSelectView(discord.ui.View):
    def __init__(self, testimonial_channel_id: int, guild: discord.Guild, role_id: int = None):
        super().__init__(timeout=60)
        self.testimonial_channel_id = testimonial_channel_id
        self.guild = guild
        self.role_id = role_id

        # Build user options based on role
        if role_id:
            role = guild.get_role(role_id)
            members = [m for m in role.members if not m.bot] if role else []
        else:
            members = [m for m in guild.members if not m.bot]

        if members:
            options = [discord.SelectOption(label=m.display_name, value=str(m.id)) for m in members]
            select = discord.ui.Select(
                placeholder="Select a user to review",
                min_values=1,
                max_values=1,
                options=options,
                custom_id="user_select_filtered"
            )
            select.callback = self.select_user
            self.add_item(select)
        else:
            select = discord.ui.Select(
                placeholder="No users available to review",
                min_values=1,
                max_values=1,
                options=[discord.SelectOption(label="No users available", value="none", default=True)],
                disabled=True
            )
            self.add_item(select)

    async def select_user(self, interaction: discord.Interaction):
        user_id = int(interaction.data['values'][0])
        target_user = self.guild.get_member(user_id)
        if not target_user:
            await interaction.response.send_message("❌ User not found.", ephemeral=True)
            return

        await interaction.response.send_modal(ReviewModal(target_user, self.testimonial_channel_id))


class ReviewButtonView(discord.ui.View):
    def __init__(self, testimonial_channel_id: int, guild: discord.Guild, role_id: int = None):
        super().__init__(timeout=None)
        self.testimonial_channel_id = testimonial_channel_id
        self.guild = guild
        self.role_id = role_id

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
                guild=self.guild,
                role_id=self.role_id
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
        # Restore persistent buttons on bot restart
        settings = load_settings()
        for guild_id_str, data in settings.items():
            guild = self.get_guild(int(guild_id_str))
            if not guild:
                continue

            testimonial_channel_id = data.get("testimonial_channel")
            role_id = data.get("reviewable_role")
            review_channel_id = data.get("review_channel")
            review_message_id = data.get("review_message_id")

            if testimonial_channel_id and review_channel_id and review_message_id:
                review_channel = guild.get_channel(review_channel_id)
                if review_channel:
                    try:
                        message = await review_channel.fetch_message(review_message_id)
                        view = ReviewButtonView(testimonial_channel_id, guild, role_id)
                        self.add_view(view)
                        await message.edit(view=view)
                    except discord.NotFound:
                        print(f"Original review message {review_message_id} not found in guild {guild.name}.")

    async def on_ready(self):
        print(f"✅ Logged in as {self.user} (ID: {self.user.id})")
        await self.tree.sync()


bot = ReviewBot()


# Settings command
@bot.tree.command(name="settings", description="Manage settings")
@discord.app_commands.default_permissions(administrator=True)
@app_commands.describe(action="Choose an action", channel="The channel to assign (if applicable)", role="The role whose members can be reviewed")
@app_commands.choices(action=[
    app_commands.Choice(name="Set Review Channel", value="set_review_channel"),
    app_commands.Choice(name="Set Testimonial Channel", value="set_testimonial_channel"),
    app_commands.Choice(name="Set Staff Role", value="set_reviewable_role"),
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

        if testimonial_id:
            embed = discord.Embed(title="💬 Leave a Review", description="Click the button below to submit your testimonial.", color=discord.Color.blurple())
            message = await channel.send(embed=embed, view=ReviewButtonView(testimonial_id, interaction.guild, role_id))
            settings[guild_id]["review_message_id"] = message.id
            save_settings(settings)

            bot.add_view(ReviewButtonView(testimonial_id, interaction.guild, role_id))

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

    elif action.value == "clear":
        settings.pop(guild_id, None)
        save_settings(settings)
        await interaction.response.send_message("✅ Settings cleared.", ephemeral=True)

    elif action.value == "list":
        current_review = settings.get(guild_id, {}).get("review_channel")
        current_testimonial = settings.get(guild_id, {}).get("testimonial_channel")
        current_role = settings.get(guild_id, {}).get("reviewable_role")

        msg = ""
        msg += f"💬 Review channel: {interaction.guild.get_channel(current_review).mention if current_review else 'Not set'}\n"
        msg += f"📝 Testimonial channel: {interaction.guild.get_channel(current_testimonial).mention if current_testimonial else 'Not set'}\n"
        msg += f"👤 Staff role: {interaction.guild.get_role(current_role).mention if current_role else 'Not set'}\n"

        await interaction.response.send_message(msg, ephemeral=True)


# Generate command
@bot.tree.command(name="generate", description="Post the review embed in the configured review channel")
@discord.app_commands.default_permissions(administrator=True)
@app_commands.checks.has_permissions(manage_guild=True)
async def generate_review_post(interaction: discord.Interaction):
    guild_id = str(interaction.guild.id)
    settings = load_settings()
    role_id = settings.get(guild_id, {}).get("reviewable_role")

    if (guild_id not in settings or "review_channel" not in settings[guild_id] or "testimonial_channel" not in settings[guild_id]):
        await interaction.response.send_message("❌ You must set both the review and testimonial channels first using `/settings`.", ephemeral=True)
        return

    review_channel_id = settings[guild_id]["review_channel"]
    testimonial_channel_id = settings[guild_id]["testimonial_channel"]
    review_channel = interaction.guild.get_channel(review_channel_id)

    if review_channel is None:
        await interaction.response.send_message("❌ Review channel not found. Please reconfigure `/settings`.", ephemeral=True)
        return

    embed = discord.Embed(title="💬 Leave a Review", description="Click the button below to review someone in this server.", color=discord.Color.blurple())
    view = ReviewButtonView(testimonial_channel_id, interaction.guild, role_id)
    message = await review_channel.send(embed=embed, view=view)

    # Save message ID for persistence
    if guild_id not in settings:
        settings[guild_id] = {}
    settings[guild_id]["review_message_id"] = message.id
    save_settings(settings)

    bot.add_view(view)
    await interaction.response.send_message(f"✅ Review embed posted in {review_channel.mention}", ephemeral=True)

bot.run(TOKEN)