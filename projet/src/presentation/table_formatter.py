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

    def _create_table(self, title: str, address: Address, show_breakdown: bool = False) -> Table:
        """Crée un tableau de base pour les relations."""
        table = Table(
            title=f"{title} - {address.address[:20]}...",
            show_header=True,
            header_style="bold cyan"
        )
        table.add_column("Target Address", style="dim", min_width=20)
        
        if show_breakdown:
            # Nouveau format avec breakdown du scoring
            table.add_column("Act", justify="right", width=6)  # Activity
            table.add_column("Prox", justify="right", width=6)  # Proximity
            table.add_column("Rec", justify="right", width=6)  # Recency
            table.add_column("Dir", justify="right", width=6)  # Direct (total)
        else:
            table.add_column("Direct", justify="right", width=8)
            
        table.add_column("Indirecte", justify="right", width=10)
        table.add_column("Total", justify="right", width=8)
        table.add_column("Tx Count", justify="right", width=8)
        table.add_column("Volume (ETH)", justify="right", width=12)
        return table

    def _add_relationship_row(self, table: Table, rel: RelationshipScore, show_breakdown: bool = False):
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

        # Style pour le score propagé (bleu si significatif)
        prop_style = "cyan" if rel.propagated_score >= 20 else "dim"
        
        # Récupérer le breakdown si disponible
        breakdown = rel.metrics.get('score_breakdown', {})

        if show_breakdown and breakdown:
            # Style pour les composantes
            act_style = "green" if breakdown.get('activity', 0) >= 50 else "dim"
            prox_style = "blue" if breakdown.get('proximity', 0) >= 50 else "dim"
            rec_style = "yellow" if breakdown.get('recency', 0) >= 50 else "dim"
            
            table.add_row(
                target_short,
                f"[{act_style}]{breakdown.get('activity', 0):.0f}[/{act_style}]",
                f"[{prox_style}]{breakdown.get('proximity', 0):.0f}[/{prox_style}]",
                f"[{rec_style}]{breakdown.get('recency', 0):.0f}[/{rec_style}]",
                f"{rel.direct_score:.1f}",
                f"[{prop_style}]{rel.propagated_score:.1f}[/{prop_style}]" if rel.propagated_score > 0 else "-",
                f"[{score_style}]{rel.total_score:.1f}[/{score_style}]",
                str(tx_count) if tx_count else "-",
                f"{volume:.4f}" if volume else "-"
            )
        else:
            table.add_row(
                target_short,
                f"{rel.direct_score:.1f}",
                f"[{prop_style}]{rel.propagated_score:.1f}[/{prop_style}]" if rel.propagated_score > 0 else "-",
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
        limit: int = 10,
        show_breakdown: bool = True
    ):
        """
        Affiche les deux tableaux côte à côte.
        
        Args:
            show_breakdown: Si True, affiche les composantes du scoring (Act/Prox/Rec)
        """
        # Légende du scoring
        if show_breakdown:
            self.console.print("\n[dim]Score breakdown: Act=Activity (50%), Prox=Proximity (30%), Rec=Recency (20%)[/dim]")
        
        # Table 1
        t1 = self._create_table("Address 1 Relations", table1.main_address, show_breakdown=show_breakdown)
        for rel in table1.get_top_relationships(limit):
            self._add_relationship_row(t1, rel, show_breakdown=show_breakdown)

        # Table 2
        t2 = self._create_table("Address 2 Relations", table2.main_address, show_breakdown=show_breakdown)
        for rel in table2.get_top_relationships(limit):
            self._add_relationship_row(t2, rel, show_breakdown=show_breakdown)

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
            content.append(f"  Indirecte Score: {rel1.propagated_score:.2f}")
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

    def display_expanded_node_relationships(
        self,
        console: Console,
        address1: Address,
        address2: Address,
        table1: AddressRelationshipTable,
        table2: AddressRelationshipTable,
        limit: int = 10
    ):
        """Affiche les relations entre les adresses principales et les nœuds d'expansion.

        Cette méthode montre les scores de relation pour tous les nouveaux nœuds
        ajoutés par l'expansion du graphe, pas seulement entre les 2 adresses principales.
        """
        # Identifier les nœuds d'expansion (tous sauf les 2 adresses principales)
        expanded_nodes_1 = [
            rel for rel in table1.relationships.values()
            if rel.target.address != address2.address
        ]
        expanded_nodes_2 = [
            rel for rel in table2.relationships.values()
            if rel.target.address != address1.address
        ]

        if not expanded_nodes_1 and not expanded_nodes_2:
            return

        console.print("\n")
        console.print(Panel(
            "[bold cyan]Relations avec les nœuds d'expansion[/bold cyan]",
            border_style="cyan"
        ))

        # Trier par score total décroissant
        expanded_nodes_1.sort(key=lambda r: r.total_score, reverse=True)
        expanded_nodes_2.sort(key=lambda r: r.total_score, reverse=True)

        # Tableau pour l'adresse 1
        if expanded_nodes_1:
            table_addr1 = Table(
                title=f"Relations de {address1.address[:20]}... avec nœuds d'expansion",
                show_header=True,
                header_style="bold cyan"
            )
            table_addr1.add_column("Nœud", style="dim", min_width=20)
            table_addr1.add_column("Direct", justify="right", width=8)
            table_addr1.add_column("Indirecte", justify="right", width=10)
            table_addr1.add_column("Total", justify="right", width=8)
            table_addr1.add_column("Tx", justify="right", width=6)
            table_addr1.add_column("Volume (ETH)", justify="right", width=12)

            for rel in expanded_nodes_1[:limit]:
                target_short = rel.target.address[:20] + "..."
                score_style = self._score_color(rel.total_score)
                prop_style = "cyan" if rel.propagated_score >= 20 else "dim"
                tx_count = rel.metrics.get('tx_count', 0)
                volume = rel.metrics.get('total_volume', 0)

                table_addr1.add_row(
                    target_short,
                    f"{rel.direct_score:.1f}",
                    f"[{prop_style}]{rel.propagated_score:.1f}[/{prop_style}]" if rel.propagated_score > 0 else "-",
                    f"[{score_style}]{rel.total_score:.1f}[/{score_style}]",
                    str(tx_count) if tx_count else "-",
                    f"{volume:.4f}" if volume else "-"
                )

            console.print(table_addr1)

        # Tableau pour l'adresse 2
        if expanded_nodes_2:
            table_addr2 = Table(
                title=f"Relations de {address2.address[:20]}... avec nœuds d'expansion",
                show_header=True,
                header_style="bold cyan"
            )
            table_addr2.add_column("Nœud", style="dim", min_width=20)
            table_addr2.add_column("Direct", justify="right", width=8)
            table_addr2.add_column("Indirecte", justify="right", width=10)
            table_addr2.add_column("Total", justify="right", width=8)
            table_addr2.add_column("Tx", justify="right", width=6)
            table_addr2.add_column("Volume (ETH)", justify="right", width=12)

            for rel in expanded_nodes_2[:limit]:
                target_short = rel.target.address[:20] + "..."
                score_style = self._score_color(rel.total_score)
                prop_style = "cyan" if rel.propagated_score >= 20 else "dim"
                tx_count = rel.metrics.get('tx_count', 0)
                volume = rel.metrics.get('total_volume', 0)

                table_addr2.add_row(
                    target_short,
                    f"{rel.direct_score:.1f}",
                    f"[{prop_style}]{rel.propagated_score:.1f}[/{prop_style}]" if rel.propagated_score > 0 else "-",
                    f"[{score_style}]{rel.total_score:.1f}[/{score_style}]",
                    str(tx_count) if tx_count else "-",
                    f"{volume:.4f}" if volume else "-"
                )

            console.print(table_addr2)
