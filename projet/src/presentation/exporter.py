"""Export des tableaux de relation vers différents formats."""
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import List

from src.domain.models import AddressRelationshipTable, RelationshipScore


class RelationshipTableExporter:
    """Exporte les tableaux de relation vers JSON ou CSV."""

    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def _relationship_to_dict(self, rel: RelationshipScore) -> dict:
        """Convertit une relation en dictionnaire."""
        return {
            "source": rel.source.address,
            "target": rel.target.address,
            "score": rel.direct_score,
            "metrics": {
                k: v for k, v in rel.metrics.items()
                if k not in ('score_breakdown',)  # Exclure les objets complexes
            }
        }

    def _table_to_dict(self, table: AddressRelationshipTable) -> dict:
        """Convertit un tableau en dictionnaire."""
        return {
            "main_address": table.main_address.address,
            "relationships": [
                self._relationship_to_dict(rel)
                for rel in table.relationships.values()
            ],
            "top_relationships": [
                self._relationship_to_dict(rel)
                for rel in table.get_top_relationships(10)
            ]
        }

    def export(self, tables: List[AddressRelationshipTable], format: str = "json", filename: str = None) -> str:
        """
        Exporte les tableaux vers un fichier.

        Args:
            tables: Liste des tableaux à exporter
            format: 'json' ou 'csv'
            filename: Nom de fichier personnalisé (sans extension). Si None, utilise un timestamp.

        Returns:
            Chemin du fichier généré
        """
        # Si le dossier parent est déjà timestampé (ex: output/20240313_120000),
        # on n'ajoute pas de timestamp supplémentaire au fichier
        parent_is_timestamped = False
        try:
            # Vérifie si le nom du dossier parent ressemble à un timestamp
            parent_name = self.output_dir.name
            if len(parent_name) == 15 and parent_name[8] == '_':  # Format YYYYMMDD_HHMMSS
                int(parent_name[:8])  # Vérifie que c'est des chiffres
                int(parent_name[9:])  # Vérifie que c'est des chiffres
                parent_is_timestamped = True
        except (ValueError, IndexError):
            pass

        if filename is None:
            if parent_is_timestamped:
                filename = "data"  # Nom simple si dossier déjà timestampé
            else:
                filename = datetime.now().strftime("%Y%m%d_%H%M%S")

        if format == "json":
            return self._export_json(tables, filename)
        elif format == "csv":
            return self._export_csv(tables, filename)
        else:
            raise ValueError(f"Format non supporté: {format}")

    def _export_json(self, tables: List[AddressRelationshipTable], filename: str) -> str:
        """Exporte vers JSON."""
        data = {
            "timestamp": filename,
            "tables": [self._table_to_dict(t) for t in tables]
        }

        filepath = self.output_dir / f"relationships_{filename}.json"
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        return str(filepath)

    def _export_csv(self, tables: List[AddressRelationshipTable], filename: str) -> str:
        """Exporte vers CSV (une ligne par relation)."""
        filepath = self.output_dir / f"relationships_{filename}.csv"

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'main_address', 'target_address', 'score',
                'total_score', 'tx_count', 'volume_eth'
            ])

            for table in tables:
                for rel in table.relationships.values():
                    writer.writerow([
                        table.main_address.address,
                        rel.target.address,
                        rel.direct_score,
                        rel.total_score,
                        rel.metrics.get('tx_count', 0),
                        rel.metrics.get('total_volume', 0)
                    ])

        return str(filepath)
