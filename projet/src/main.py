"""Point d'entrée principal avec affichage des tableaux de corrélation."""
import os
import re
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Prompt, IntPrompt, Confirm
from rich.table import Table
from rich import box

from src.config import config
from src.adapters.dune import DuneAdapter
from src.services.correlation import CorrelationService
from src.domain.models import Address
from src.presentation.table_formatter import RelationshipTableFormatter
from src.presentation.exporter import RelationshipTableExporter


def is_valid_ethereum_address(address: str) -> bool:
    """Vérifie si une chaîne est une adresse Ethereum valide."""
    if not address:
        return False
    # Retirer le préfixe 0x s'il existe pour la vérification
    addr_clean = address.lower().replace('0x', '')
    # Vérifier que c'est une chaîne hexadécimale de 40 caractères
    return len(addr_clean) == 40 and all(c in '0123456789abcdef' for c in addr_clean)


def get_address_with_validation(console: Console, prompt_text: str, default: str = None) -> str:
    """Demande une adresse Ethereum avec validation."""
    while True:
        if default:
            address = Prompt.ask(prompt_text, default=default, console=console)
        else:
            address = Prompt.ask(prompt_text, console=console)

        # Nettoyer l'adresse
        address = address.strip().lower()

        if not address.startswith('0x'):
            address = '0x' + address

        if is_valid_ethereum_address(address):
            return address
        else:
            console.print("[red]✗ Adresse invalide. Une adresse Ethereum doit faire 42 caractères (0x + 40 hex).[/red]")


def interactive_config(console: Console) -> dict:
    """Configure interactivement les paramètres de l'analyse."""

    console.print(Panel.fit(
        "[bold cyan]Ethereum Address Correlation Tool[/bold cyan]\n"
        "[dim]Analyse des relations entre adresses Ethereum[/dim]",
        border_style="cyan"
    ))

    if not config.DUNE_API_KEY:
        console.print("[yellow]WARNING: DUNE_API_KEY not found in environment variables.[/yellow]")

    console.print("\n[bold cyan]═══════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]  Configuration de l'analyse[/bold cyan]")
    console.print("[bold cyan]═══════════════════════════════════════════════════[/bold cyan]\n")

    # === ADRESSES ===
    console.print("[bold green]1. Adresses à analyser[/bold green]")

    default_addr1 = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045"  # vitalik.eth
    default_addr2 = "0xF8fc9A91349eBd2033d53F2B97245102f00ABa96"

    use_defaults = Confirm.ask(
        "Utiliser les adresses par défaut ?",
        default=True,
        console=console
    )

    if use_defaults:
        address1 = default_addr1
        address2 = default_addr2
        console.print(f"  [dim]Adresse 1: {address1}[/dim]")
        console.print(f"  [dim]Adresse 2: {address2}[/dim]")
    else:
        address1 = get_address_with_validation(
            console,
            "Adresse Ethereum 1",
            default=default_addr1
        )
        address2 = get_address_with_validation(
            console,
            "Adresse Ethereum 2",
            default=default_addr2
        )

    # === PARAMÈTRES D'EXPANSION ===
    console.print("\n[bold green]2. Paramètres d'expansion du graphe[/bold green]")

    expansion_depth = IntPrompt.ask(
        "  Profondeur d'expansion (1 = base seule, 2 = 1 niveau, 3 = 2 niveaux...)",
        default=2,
        console=console
    )

    top_n = IntPrompt.ask(
        "  Nombre de nœuds à sélectionner par niveau d'expansion",
        default=3,
        console=console
    )

    base_tx_limit = IntPrompt.ask(
        "  Nombre de transactions à récupérer pour la base (adresses principales)",
        default=5,
        console=console
    )

    expansion_tx_limit = IntPrompt.ask(
        "  Nombre de transactions à récupérer pour l'expansion (nœuds découverts)",
        default=3,
        console=console
    )

    # === OPTIONS DE SORTIE ===
    console.print("\n[bold green]3. Options de sortie[/bold green]")

    show_matplotlib = Confirm.ask(
        "  Afficher le graphique matplotlib ?",
        default=True,
        console=console
    )

    generate_interactive = Confirm.ask(
        "  Générer le graphique interactif HTML ?",
        default=True,
        console=console
    )

    auto_open_browser = False
    if generate_interactive:
        auto_open_browser = Confirm.ask(
            "    Ouvrir automatiquement dans le navigateur ?",
            default=False,
            console=console
        )

    export_json = Confirm.ask(
        "  Exporter les données en JSON ?",
        default=True,
        console=console
    )

    export_csv = Confirm.ask(
        "  Exporter les données en CSV ?",
        default=True,
        console=console
    )

    # === RÉCAPITULATIF ===
    console.print("\n[bold cyan]═══════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]  Récapitulatif[/bold cyan]")
    console.print("[bold cyan]═══════════════════════════════════════════════════[/bold cyan]")

    summary = Table(box=box.ROUNDED, show_header=False)
    summary.add_column("Paramètre", style="cyan")
    summary.add_column("Valeur", style="white")

    summary.add_row("Adresse 1", f"[yellow]{address1[:20]}...{address1[-8:]}[/yellow]")
    summary.add_row("Adresse 2", f"[yellow]{address2[:20]}...{address2[-8:]}[/yellow]")
    summary.add_row("Profondeur d'expansion", str(expansion_depth))
    summary.add_row("Top N par niveau", str(top_n))
    summary.add_row("Limite transactions (base)", str(base_tx_limit))
    summary.add_row("Limite transactions (expansion)", str(expansion_tx_limit))
    summary.add_row("Graphique matplotlib", "✓ Oui" if show_matplotlib else "✗ Non")
    summary.add_row("Graphique interactif", "✓ Oui" if generate_interactive else "✗ Non")
    summary.add_row("Export JSON", "✓ Oui" if export_json else "✗ Non")
    summary.add_row("Export CSV", "✓ Oui" if export_csv else "✗ Non")

    console.print(summary)

    confirm = Confirm.ask(
        "\n[bold]Lancer l'analyse avec ces paramètres ?[/bold]",
        default=True,
        console=console
    )

    if not confirm:
        console.print("[yellow]Analyse annulée.[/yellow]")
        return None

    return {
        'address1': address1,
        'address2': address2,
        'expansion_depth': expansion_depth,
        'top_n': top_n,
        'base_tx_limit': base_tx_limit,
        'expansion_tx_limit': expansion_tx_limit,
        'show_matplotlib': show_matplotlib,
        'generate_interactive': generate_interactive,
        'auto_open_browser': auto_open_browser,
        'export_json': export_json,
        'export_csv': export_csv,
    }


def run_analysis(console: Console, params: dict):
    """Exécute l'analyse avec les paramètres fournis."""

    address1 = Address(params['address1'])
    address2 = Address(params['address2'])

    console.print(f"\n[bold]Analyse des corrélations entre :[/bold]")
    console.print(f"  <:> Adresse 1: [yellow]{address1.address}[/yellow]")
    console.print(f"   :")
    console.print(f"  <:> Adresse 2: [yellow]{address2.address}[/yellow]")

    # Construction du graphe et calcul des scores
    dune_adapter = DuneAdapter()
    correlation_service = CorrelationService(dune_adapter)

    # Paramètres d'expansion
    expansion_depth = params['expansion_depth']
    top_n = params['top_n']
    base_tx_limit = params['base_tx_limit']
    expansion_tx_limit = params['expansion_tx_limit']

    # Construction du graphe avec expansion et calcul des scores
    with console.status("[bold green]Construction du graphe et expansion..."):
        table1, table2 = correlation_service.build_graph_with_expansion(
            address1, address2,
            expansion_depth=expansion_depth,
            top_n=top_n,
            base_tx_limit=base_tx_limit,
            expansion_tx_limit=expansion_tx_limit
        )

    # Affichage des tableaux
    formatter = RelationshipTableFormatter(console)

    console.print("\n")
    formatter.display_both_tables(table1, table2, limit=10)

    # Affichage des relations avec les nœuds d'expansion
    formatter.display_expanded_node_relationships(console, address1, address2, table1, table2)

    # Calcul et affichage du score de corrélation global
    result = correlation_service.calculate_score(address1, address2, expansion_depth=expansion_depth, top_n=top_n, base_tx_limit=base_tx_limit, expansion_tx_limit=expansion_tx_limit)

    # Affichage du résumé
    formatter.display_summary(address1, address2, result.score, table1, table2)

    # Visualisation (générer d'abord pour obtenir le dossier de sortie)
    console.print("\n[bold]Génération des visualisations...[/bold]")

    output_dir = None

    if params.get('show_matplotlib'):
        console.print("  [dim]Graphique statique matplotlib...[/dim]")
        correlation_service.visualize_graph(address1, address2)

    if params.get('generate_interactive'):
        console.print("  [dim]Graphique interactif HTML...[/dim]")
        try:
            html_path = correlation_service.visualize_interactive(
                address1, address2,
                tables=[table1, table2],
                auto_open=params.get('auto_open_browser', False),
                params={
                    'expansion_depth': params['expansion_depth'],
                    'top_n': params['top_n'],
                    'base_tx_limit': params['base_tx_limit'],
                    'expansion_tx_limit': params['expansion_tx_limit'],
                }
            )
            console.print(f"  [green]✓[/green] Interactif: [dim]{html_path}[/dim]")
            # Extraire le dossier de sortie (dossier parent du fichier HTML)
            from pathlib import Path
            output_dir = str(Path(html_path).parent)
        except Exception as e:
            console.print(f"  [yellow]✗[/yellow] Échec: {e}")

    # Export des données pour réutilisation (dans le même dossier que le HTML)
    if params.get('export_json') or params.get('export_csv'):
        console.print("\n[bold]Export des données...[/bold]")
        from datetime import datetime

        # Utiliser un timestamp unique pour tous les exports
        export_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        exporter = RelationshipTableExporter(output_dir=output_dir if output_dir else "output")

        if params.get('export_json'):
            try:
                json_path = exporter.export([table1, table2], format="json", filename=export_timestamp)
                console.print(f"  JSON: [dim]{json_path}[/dim]")
            except Exception as e:
                console.print(f"  Export JSON échoué: {e}")

        if params.get('export_csv'):
            try:
                csv_path = exporter.export([table1, table2], format="csv", filename=export_timestamp)
                console.print(f"  CSV: [dim]{csv_path}[/dim]")
            except Exception as e:
                console.print(f"  Export CSV échoué: {e}")

    console.print("\n[bold green]✓ Analyse terminée![/bold green]")


def main():
    console = Console()

    # Configuration interactive
    params = interactive_config(console)

    if params is None:
        return

    # Exécution de l'analyse
    try:
        run_analysis(console, params)
    except KeyboardInterrupt:
        console.print("\n[yellow]Analyse interrompue par l'utilisateur.[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Erreur lors de l'analyse: {e}[/red]")
        raise


if __name__ == "__main__":
    main()
