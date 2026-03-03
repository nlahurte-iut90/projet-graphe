"""Formatteur de tableaux pour l'affichage des relations."""
from typing import List, Optional
from rich.table import Table
from rich.console import Console
from rich.panel import Panel
from rich.columns import Columns

from src.domain.models import Address, AddressRelationshipTable, RelationshipScore


class RelationshipTableFormatter:
    """Formate et affiche les tableaux de relations."""

    def __init__(self, console: Console):
        self.console = console

    def _create_table(self, title: str, address: Address) -> Table:
        """Crée un tableau de base pour les relations."""
        table = Table(
            title=f"{title} - {address.address[:20]}...",
            show_header=True,
            header_style="bold cyan"
        )
        table.add_column("Target Address", style="dim", min_width=20)
        table.add_column("Direct", justify="right", width=8)
        table.add_column("Indirect", justify="right", width=8)
        table.add_column("Total", justify="right", width=8)
        table.add_column("Tx Count", justify="right", width=8)
        table.add_column("Volume (ETH)", justify="right", width=12)
        return table

    def _add_relationship_row(self, table: Table, rel: RelationshipScore):
        """Ajoute une ligne de relation au tableau."""
        target_short = rel.target.address[:20] + "..."

        # Color based on total score
        if rel.total_score >= 80:
            score_style = "bold green"
        elif rel.total_score >= 50:
            score_style = "yellow"
        elif rel.total_score >= 20:
            score_style = "dim yellow"
        else:
            score_style = "dim"

        tx_count = rel.metrics.get('tx_count', 0)
        volume = rel.metrics.get('total_volume', 0)

        table.add_row(
            target_short,
            f"{rel.direct_score:.1f}",
            f"{rel.indirect_score:.1f}",
            f"[{score_style}]{rel.total_score:.1f}[/{score_style}]",
            str(tx_count) if tx_count else "-",
            f"{volume:.4f}" if volume else "-"
        )

    def display_table(self, table_data: AddressRelationshipTable, limit: int = 10):
        """Affiche un tableau de relations."""
        table = self._create_table("Relationships", table_data.main_address)

        top_relationships = table_data.get_top_relationships(limit)
        for rel in top_relationships:
            self._add_relationship_row(table, rel)

        self.console.print(table)

    def display_both_tables(
        self,
        table1: AddressRelationshipTable,
        table2: AddressRelationshipTable,
        limit: int = 10
    ):
        """Affiche les deux tableaux côte à côte."""
        # Table 1
        t1 = self._create_table("Address 1 Relations", table1.main_address)
        for rel in table1.get_top_relationships(limit):
            self._add_relationship_row(t1, rel)

        # Table 2
        t2 = self._create_table("Address 2 Relations", table2.main_address)
        for rel in table2.get_top_relationships(limit):
            self._add_relationship_row(t2, rel)

        # Affichage côte à côte
        self.console.print(Columns([t1, t2]))

    def display_summary(
        self,
        address1: Address,
        address2: Address,
        score: float,
        table1: AddressRelationshipTable,
        table2: AddressRelationshipTable
    ):
        """Affiche le résumé de la corrélation."""
        # Trouver la relation directe entre les deux adresses
        rel1 = table1.get_relationship(address2)
        rel2 = table2.get_relationship(address1)

        content = []
        content.append(f"[bold]Correlation Score:[/bold] [{self._score_color(score)}]{score:.2f}[/{self._score_color(score)}]")
        content.append("")

        if rel1:
            content.append(f"[dim]From {address1.address[:15]}... perspective:[/dim]")
            content.append(f"  Direct Score: {rel1.direct_score:.2f}")
            content.append(f"  Indirect Score: {rel1.indirect_score:.2f}")
            content.append(f"  Transactions: {rel1.metrics.get('tx_count', 0)}")
            content.append(f"  Volume: {rel1.metrics.get('total_volume', 0):.4f} ETH")

        self.console.print(Panel(
            "\n".join(content),
            title="Summary",
            border_style="cyan"
        ))

    def _score_color(self, score: float) -> str:
        """Retourne la couleur selon le score."""
        if score >= 80:
            return "bold green"
        elif score >= 50:
            return "yellow"
        elif score >= 20:
            return "dim yellow"
        return "dim"
