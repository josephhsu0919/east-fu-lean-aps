from pathlib import Path

from aps.sample_data import write_demo_excel


if __name__ == "__main__":
    path = write_demo_excel(Path(__file__).resolve().parent / "data" / "EastFu_Lean_APS_Demo.xlsx")
    print(f"Demo Excel created: {path}")
