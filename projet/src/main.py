import sys
from src.config import config
from src.domain.models import Address
from src.adapters.dune import DuneAdapter
from src.services.correlation import CorrelationService
from networkx import Graph

def main():
    print("Ethereum Address Correlation Tool")
    print("---------------------------------")
    
    if not config.DUNE_API_KEY:
        print("WARNING: DUNE_API_KEY not found in environment variables.")
        # In a real app, we might exit or warn
    
    addr1_input = "0xd8da6bf26964af9d7eed9e03e53415d37aa96045" # Vitalik.eth
    addr2_input = "0xF8fc9A91349eBd2033d53F2B97245102f00ABa96" 
    
    print(f"Calculating correlation betwen {addr1_input} and {addr2_input}...")
    
    # Initialize Adapter
    dune = DuneAdapter()
    
    # Call get_transactions
    try:
       correlation_service = CorrelationService(dune)
       # Calculate score (which builds the graph)
       result = correlation_service.calculate_score(Address(addr1_input), Address(addr2_input))
       print(f"Graph built successfully.")
       print(f"Nodes: {result.details['nodes']}")
       print(f"Edges: {result.details['edges']}")
       print(f"Score: {result.score}")
       print(f"Has path: {result.details['has_path']}")
       
       # Visualize
       print("Displaying graph...")
       correlation_service.visualize_graph(Address(addr1_input), Address(addr2_input))
    except Exception as e:
        print(f"Error fetching transactions: {e}")

    

    print("Done.")

if __name__ == "__main__":
    main()
