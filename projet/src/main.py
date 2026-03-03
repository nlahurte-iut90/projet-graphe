"""Point d'entrée principal avec affichage des tableaux de corrélation."""
import os
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from src.config import config
from src.adapters.dune import DuneAdapter
from src.services.correlation import CorrelationService
from src.domain.models import Address
from src.presentation.table_formatter import RelationshipTableFormatter
from src.presentation.exporter import RelationshipTableExporter


def main():
    console = Console()

    console.print(Panel.fit(
        "[bold cyan]Ethereum Address Correlation Tool[/bold cyan]\n"
        "[dim]Analyse des relations entre adresses Ethereum[/dim]",
        border_style="cyan"
    ))

    if not config.DUNE_API_KEY:
        console.print("[yellow]WARNING: DUNE_API_KEY not found in environment variables.[/yellow]")

    # Adresses à analyser
    address1 = Address("0xd8da6bf26964af9d7eed9e03e53415d37aa96045")  # vitalik.eth
    address2 = Address("0xF8fc9A91349eBd2033d53F2B97245102f00ABa96")

    console.print(f"\n[bold]Analyse des corrélations entre :[/bold]")
    console.print(f"  <:> Adresse 1: [yellow]{address1.address}[/yellow]")
    console.print(f"   :")
    console.print(f"  <:> Adresse 2: [yellow]{address2.address}[/yellow]")

    # Construction du graphe et calcul des scores
    dune_adapter = DuneAdapter()
    correlation_service = CorrelationService(dune_adapter)

    # Paramètres d'expansion
    expansion_depth = 2  # 1 = base seule, 2 = 1 niveau d'expansion, etc.
    top_n = 3  # Nombre de nœuds à sélectionner par niveau

    with console.status("[bold green]Construction du graphe de transactions..."):
        correlation_service.build_graph(address1, address2, expansion_depth=expansion_depth, top_n=top_n)

    # Calcul des tableaux de relation pour chaque main address
    with console.status("[bold green]Calcul des scores de relation..."):
        table1 = correlation_service.calculate_relationship_scores(address1)
        table2 = correlation_service.calculate_relationship_scores(address2)

    # Affichage des tableaux
    formatter = RelationshipTableFormatter(console)

    console.print("\n")
    formatter.display_both_tables(table1, table2, limit=10)

    # Calcul et affichage du score de corrélation global
    result = correlation_service.calculate_score(address1, address2, expansion_depth=expansion_depth, top_n=top_n)

    # Affichage du résumé
    formatter.display_summary(address1, address2, result.score, table1, table2)

    # Export des données pour réutilisation
    exporter = RelationshipTableExporter()

    console.print("\n[bold]Export des données...[/bold]")
    try:
        json_path = exporter.export([table1, table2], format="json")
        console.print(f"  JSON: [dim]{json_path}[/dim]")
    except Exception as e:
        console.print(f"  Export JSON échoué: {e}")

    try:
        csv_path = exporter.export([table1, table2], format="csv")
        console.print(f"  CSV: [dim]{csv_path}[/dim]")
    except Exception as e:
        console.print(f"  Export CSV échoué: {e}")

    # Visualisation
    console.print("\n[bold]Génération des visualisations...[/bold]")

    console.print("  [dim]Graphique statique matplotlib...[/dim]")
    correlation_service.visualize_graph(address1, address2)

    console.print("  [dim]Graphique interactif HTML...[/dim]")
    try:
        html_path = correlation_service.visualize_interactive(
            address1, address2,
            tables=[table1, table2],
            auto_open=False
        )
        console.print(f"  [green]✓[/green] Interactif: [dim]{html_path}[/dim]")
    except Exception as e:
        console.print(f"  [yellow]✗[/yellow] Échec: {e}")

    console.print("\n[bold green]✓ Analyse terminée![/bold green]")


if __name__ == "__main__":
    main()
