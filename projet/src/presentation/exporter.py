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
            "direct_score": rel.direct_score,
            "indirect_score": rel.indirect_score,
            "total_score": rel.total_score,
            "metrics": {
                k: v for k, v in rel.metrics.items()
                if k != 'indirect_paths'  # Exclure les objets complexes
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

    def export(self, tables: List[AddressRelationshipTable], format: str = "json") -> str:
        """
        Exporte les tableaux vers un fichier.

        Args:
            tables: Liste des tableaux à exporter
            format: 'json' ou 'csv'

        Returns:
            Chemin du fichier généré
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        if format == "json":
            return self._export_json(tables, timestamp)
        elif format == "csv":
            return self._export_csv(tables, timestamp)
        else:
            raise ValueError(f"Format non supporté: {format}")

    def _export_json(self, tables: List[AddressRelationshipTable], timestamp: str) -> str:
        """Exporte vers JSON."""
        data = {
            "timestamp": timestamp,
            "tables": [self._table_to_dict(t) for t in tables]
        }

        filepath = self.output_dir / f"relationships_{timestamp}.json"
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)

        return str(filepath)

    def _export_csv(self, tables: List[AddressRelationshipTable], timestamp: str) -> str:
        """Exporte vers CSV (une ligne par relation)."""
        filepath = self.output_dir / f"relationships_{timestamp}.csv"

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                'main_address', 'target_address', 'direct_score',
                'indirect_score', 'total_score', 'tx_count', 'volume_eth'
            ])

            for table in tables:
                for rel in table.relationships.values():
                    writer.writerow([
                        table.main_address.address,
                        rel.target.address,
                        rel.direct_score,
                        rel.indirect_score,
                        rel.total_score,
                        rel.metrics.get('tx_count', 0),
                        rel.metrics.get('total_volume', 0)
                    ])

        return str(filepath)
