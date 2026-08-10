import discord
import io
import math
import networkx as nx
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont
from database import add_rp_entry, execute_query, fetch_one
from views import MarriageConfirmView, AdoptionConfirmView

BACKGROUND_COLOR = (248, 250, 252)
CHILD_EDGE_COLOR = (71, 85, 105)
MARRIAGE_EDGE_COLOR = (225, 29, 72)
NODE_FILL_COLOR = (255, 255, 255)
NODE_OUTLINE_COLOR = (30, 41, 59)
TARGET_NODE_FILL_COLOR = (219, 234, 254)
TEXT_COLOR = (15, 23, 42)
SUBTEXT_COLOR = (71, 85, 105)

NODE_WIDTH = 210
NODE_HEIGHT = 74
HORIZONTAL_GAP = 70
VERTICAL_GAP = 92
PADDING = 48

class FamilyCommands(commands.Cog):
    """All family commands."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------------------------------------------------------------ #
    #  Family tree helpers                                               #
    # ------------------------------------------------------------------ #

    async def _fetch_relationship_rows(self) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        async with self.bot.db_pool.acquire() as conn:
            marriages_result = await conn.execute(
                "SELECT spouse1_id, spouse2_id FROM marriages"
            )
            marriages = await marriages_result.fetchall()

            children_result = await conn.execute(
                "SELECT parent_id, child_id FROM children"
            )
            children = await children_result.fetchall()

        return (
            [(int(spouse1_id), int(spouse2_id)) for spouse1_id, spouse2_id in marriages],
            [(int(parent_id), int(child_id)) for parent_id, child_id in children],
        )

    def _build_family_component(
        self,
        target_id: int,
        marriages: list[tuple[int, int]],
        children: list[tuple[int, int]],
    ) -> tuple[set[int], list[tuple[int, int]], list[tuple[int, int]]]:
        graph = nx.Graph()
        graph.add_node(target_id)

        for spouse1_id, spouse2_id in marriages:
            graph.add_edge(spouse1_id, spouse2_id)

        for parent_id, child_id in children:
            graph.add_edge(parent_id, child_id)

        component = nx.node_connected_component(graph, target_id)
        component_marriages = [
            (spouse1_id, spouse2_id)
            for spouse1_id, spouse2_id in marriages
            if spouse1_id in component and spouse2_id in component
        ]
        component_children = [
            (parent_id, child_id)
            for parent_id, child_id in children
            if parent_id in component and child_id in component
        ]

        return component, component_marriages, component_children

    def _display_name_for_user(self, guild: discord.Guild, user_id: int) -> str:
        member = guild.get_member(user_id)
        if member is not None:
            return member.display_name
        return f"Unknown User\n{user_id}"

    def _load_font(self, size: int, *, bold: bool = False) -> ImageFont.ImageFont:
        font_names = (
            ("arialbd.ttf", "Arial Bold.ttf") if bold else ("arial.ttf", "Arial.ttf")
        )
        for font_name in font_names:
            try:
                return ImageFont.truetype(font_name, size)
            except OSError:
                continue
        return ImageFont.load_default()

    def _wrap_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_width: int,
    ) -> list[str]:
        lines: list[str] = []
        for raw_line in text.splitlines():
            words = raw_line.split()
            if not words:
                lines.append("")
                continue

            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                if draw.textlength(candidate, font=font) <= max_width:
                    current = candidate
                else:
                    lines.append(current)
                    current = word
            lines.append(current)

        return lines[:2]

    def _layout_family_tree(
        self,
        target_id: int,
        nodes: set[int],
        marriages: list[tuple[int, int]],
        children: list[tuple[int, int]],
    ) -> dict[int, tuple[float, float]]:
        undirected = nx.Graph()
        undirected.add_nodes_from(nodes)
        undirected.add_edges_from(marriages)
        undirected.add_edges_from(children)

        generations: dict[int, int] = {target_id: 0}
        queue = [target_id]
        while queue:
            current_id = queue.pop(0)
            current_generation = generations[current_id]
            for parent_id, child_id in children:
                if child_id == current_id and parent_id not in generations:
                    generations[parent_id] = current_generation - 1
                    queue.append(parent_id)
                if parent_id == current_id and child_id not in generations:
                    generations[child_id] = current_generation + 1
                    queue.append(child_id)

            for spouse1_id, spouse2_id in marriages:
                if spouse1_id == current_id and spouse2_id not in generations:
                    generations[spouse2_id] = current_generation
                    queue.append(spouse2_id)
                if spouse2_id == current_id and spouse1_id not in generations:
                    generations[spouse1_id] = current_generation
                    queue.append(spouse1_id)

        for node_id in nodes:
            generations.setdefault(node_id, 0)

        rows: dict[int, list[int]] = {}
        for node_id, generation in generations.items():
            rows.setdefault(generation, []).append(node_id)

        positions: dict[int, tuple[float, float]] = {}
        sorted_generations = sorted(rows)
        for row_index, generation in enumerate(sorted_generations):
            row_nodes = rows[generation]
            row_nodes.sort(
                key=lambda node_id: (
                    nx.shortest_path_length(undirected, target_id, node_id),
                    node_id,
                )
            )
            row_width = len(row_nodes) * NODE_WIDTH + (len(row_nodes) - 1) * HORIZONTAL_GAP
            start_x = -row_width / 2 + NODE_WIDTH / 2
            y = row_index * (NODE_HEIGHT + VERTICAL_GAP)
            for column_index, node_id in enumerate(row_nodes):
                x = start_x + column_index * (NODE_WIDTH + HORIZONTAL_GAP)
                positions[node_id] = (x, y)

        return positions

    def _render_family_tree_image(
        self,
        guild: discord.Guild,
        target_id: int,
        nodes: set[int],
        marriages: list[tuple[int, int]],
        children: list[tuple[int, int]],
    ) -> io.BytesIO:
        positions = self._layout_family_tree(target_id, nodes, marriages, children)
        min_x = min(x for x, _ in positions.values()) - NODE_WIDTH / 2
        max_x = max(x for x, _ in positions.values()) + NODE_WIDTH / 2
        min_y = min(y for _, y in positions.values()) - NODE_HEIGHT / 2
        max_y = max(y for _, y in positions.values()) + NODE_HEIGHT / 2

        width = max(360, math.ceil(max_x - min_x + PADDING * 2))
        height = max(220, math.ceil(max_y - min_y + PADDING * 2))
        offset_x = PADDING - min_x
        offset_y = PADDING - min_y

        image = Image.new("RGB", (width, height), BACKGROUND_COLOR)
        draw = ImageDraw.Draw(image)
        title_font = self._load_font(18, bold=True)
        body_font = self._load_font(15)
        subtext_font = self._load_font(11)

        def shifted(node_id: int) -> tuple[float, float]:
            x, y = positions[node_id]
            return x + offset_x, y + offset_y

        for parent_id, child_id in children:
            parent_x, parent_y = shifted(parent_id)
            child_x, child_y = shifted(child_id)
            draw.line(
                (
                    parent_x,
                    parent_y + NODE_HEIGHT / 2,
                    child_x,
                    child_y - NODE_HEIGHT / 2,
                ),
                fill=CHILD_EDGE_COLOR,
                width=3,
            )

        for spouse1_id, spouse2_id in marriages:
            spouse1_x, spouse1_y = shifted(spouse1_id)
            spouse2_x, spouse2_y = shifted(spouse2_id)
            draw.line(
                (
                    spouse1_x,
                    spouse1_y,
                    spouse2_x,
                    spouse2_y,
                ),
                fill=MARRIAGE_EDGE_COLOR,
                width=4,
            )

        for node_id in sorted(nodes):
            x, y = shifted(node_id)
            left = x - NODE_WIDTH / 2
            top = y - NODE_HEIGHT / 2
            right = x + NODE_WIDTH / 2
            bottom = y + NODE_HEIGHT / 2
            fill = TARGET_NODE_FILL_COLOR if node_id == target_id else NODE_FILL_COLOR
            draw.rounded_rectangle(
                (left, top, right, bottom),
                radius=10,
                fill=fill,
                outline=NODE_OUTLINE_COLOR,
                width=2,
            )

            display_name = self._display_name_for_user(guild, node_id)
            name_lines = self._wrap_text(draw, display_name, body_font, NODE_WIDTH - 28)
            total_text_height = len(name_lines) * 18 + 14
            text_y = y - total_text_height / 2
            for line in name_lines:
                line_width = draw.textlength(line, font=body_font)
                draw.text(
                    (x - line_width / 2, text_y),
                    line,
                    fill=TEXT_COLOR,
                    font=body_font,
                )
                text_y += 18

            user_id_text = str(node_id)
            user_id_width = draw.textlength(user_id_text, font=subtext_font)
            draw.text(
                (x - user_id_width / 2, text_y + 2),
                user_id_text,
                fill=SUBTEXT_COLOR,
                font=subtext_font,
            )

        title = f"{self._display_name_for_user(guild, target_id).splitlines()[0]}'s family tree"
        title_width = draw.textlength(title, font=title_font)
        draw.text(
            ((width - title_width) / 2, 12),
            title,
            fill=TEXT_COLOR,
            font=title_font,
        )

        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        return output

    @app_commands.command(name="familytree", description="Show a user's family tree as an image.")
    @app_commands.guild_only()
    @app_commands.describe(user="Whose family tree to show")
    async def family_tree(
        self,
        interaction: discord.Interaction,
        user: discord.User = None,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "That command only works inside a server.",
                ephemeral=True,
            )
            return

        target = user or interaction.user
        await interaction.response.defer(thinking=True)

        marriages, children = await self._fetch_relationship_rows()
        nodes, component_marriages, component_children = self._build_family_component(
            target.id,
            marriages,
            children,
        )
        image_data = self._render_family_tree_image(
            guild,
            target.id,
            nodes,
            component_marriages,
            component_children,
        )
        file = discord.File(
            image_data,
            filename=f"family_tree_{target.id}.png",
        )
        await interaction.followup.send(
            f"Family tree for **{target.display_name}**",
            file=file,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="marry", description="Propose to marry another user.")
    @app_commands.guild_only()
    @app_commands.describe(user="Who to marry")
    async def marry(self, interaction: discord.Interaction, user: discord.User):
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't marry yourself... </3")
            return

        if user.bot:
            await interaction.response.send_message("We marrying clankers now? :wilted_rose: :sob: :v:")
            return

        proposee_id = interaction.user.id
        proposed_id = user.id
        marriage_candidates = [proposee_id, proposed_id]
        marriage_candidates.sort()

        existing_marriage = await fetch_one("SELECT 1 FROM marriages WHERE spouse1_id = ? AND spouse2_id = ?", (marriage_candidates[0], marriage_candidates[1]))

        if existing_marriage:
            await interaction.response.send_message(f"Silly! You're already happily (hopefully) married with **{user.display_name}**!")
            return

        existing_spouse = await fetch_one(
            "SELECT 1 FROM marriages WHERE spouse1_id IN (?, ?) OR spouse2_id IN (?, ?)",
            (
                marriage_candidates[0],
                marriage_candidates[1],
                marriage_candidates[0],
                marriage_candidates[1],
            ),
        )

        if existing_spouse:
            await interaction.response.send_message("One of you is already married. Divorce first before proposing again.")
            return

        await interaction.response.send_message(view=MarriageConfirmView(interaction, user)) 

    @app_commands.command(name="divorce", description="Divorce a user you have married.")
    @app_commands.guild_only()
    @app_commands.describe(user="Who to divorce")
    async def divorce(self, interaction: discord.Interaction, user: discord.User):
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't divorce yourself...")
            return

        divorcer_id = interaction.user.id
        divorcee_id = user.id
        divorce_user_ids = [divorcer_id, divorcee_id]
        divorce_user_ids.sort()

        existing_marriage = await fetch_one("SELECT 1 FROM marriages WHERE spouse1_id = ? AND spouse2_id = ?", (divorce_user_ids[0], divorce_user_ids[1]))

        if not existing_marriage:
            await interaction.response.send_message(f"You're not married with **{user.display_name}**!")
            return

        await interaction.response.send_message(f"</3 {user.mention}, I'm sorry to say, but {interaction.user.mention} has decided to divorce you...")
        await execute_query("DELETE FROM marriages WHERE spouse1_id = ? AND spouse2_id = ?", (divorce_user_ids[0], divorce_user_ids[1]))
    
    @app_commands.command(name="adopt", description="Adopt a user as your child.")
    @app_commands.guild_only()
    @app_commands.describe(user="Who to adopt")
    async def adopt(self, interaction: discord.Interaction, user: discord.User):
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't adopt yourself...")
            return

        if user.bot:
            await interaction.response.send_message("We adopting clankers now? :wilted_rose: :sob: :v:")
            return
        
        soon_to_be_parent_id = interaction.user.id
        soon_to_be_child_id = user.id

        existing_offspring = await fetch_one("SELECT 1 FROM children WHERE child_id = ? AND parent_id = ?", (soon_to_be_child_id, soon_to_be_parent_id))

        if existing_offspring:
            await interaction.response.send_message(f"Nuh uh! You already have adopted **{user.display_name}** as your child!")
            return

        existing_parent = await fetch_one(
            "SELECT 1 FROM children WHERE child_id = ?",
            (soon_to_be_child_id,),
        )

        if existing_parent:
            await interaction.response.send_message(f"**{user.display_name}** already has a parent!")
            return

        await interaction.response.send_message(view=AdoptionConfirmView(interaction, user)) 
    
    @app_commands.command(name="disown", description="Disown a child of yours.")
    @app_commands.guild_only()
    @app_commands.describe(user="Who to disown")
    async def disown(self, interaction: discord.Interaction, user: discord.User):
        if user.id == interaction.user.id:
            await interaction.response.send_message("You can't disown yourself...")
            return

        if user.bot:
            await interaction.response.send_message("Ain't no clanker is your child... :broken_heart: :sob: :v: :wilted_rose:")
            return
        
        disowner_id = interaction.user.id
        disowned_id = user.id

        relationship = await fetch_one("SELECT 1 FROM children WHERE child_id = ? AND parent_id = ?", (disowned_id, disowner_id))

        if not relationship:
            await interaction.response.send_message(f"The user **{user.display_name}** is not your child!")
            return
        
        await interaction.response.send_message(f"</3 {user.mention}, I'm sorry to say, but {interaction.user.mention} has decided to disown you...")
        await execute_query("DELETE FROM children WHERE child_id = ? AND parent_id = ?", (disowned_id, disowner_id))

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FamilyCommands(bot))
