import discord

REQUIRED_ROLE = "Business Owner"
DEBUG_BYPASS_IDS = set()  # Discord user IDs added via debug command

UPGRADE_MESSAGE = (
    "You need the **Business Owner** role to access The Magic Closet. "
    "If you already have a subscription, make sure your Discord is linked to Patreon. "
    "If you'd like to upgrade your membership, visit our Patreon page."
)


def has_access(interaction: discord.Interaction) -> bool:
    """Check if the user has the required role or is in debug bypass."""
    user_id = str(interaction.user.id)
    if user_id in DEBUG_BYPASS_IDS:
        return True
    if not interaction.guild:
        return False
    role = discord.utils.get(interaction.user.roles, name=REQUIRED_ROLE)
    return role is not None


async def deny_access(interaction: discord.Interaction):
    """Send the upgrade message to the user."""
    await interaction.response.send_message(
        UPGRADE_MESSAGE,
        ephemeral=True
    )