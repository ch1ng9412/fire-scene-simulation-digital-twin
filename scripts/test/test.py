from src.blastfoam import generate_blastfoam_case as gbc
from src.config.setting import *
from molmass import Formula

def main():
    # 別動
    # initDirPath("minyung_blast", "minyung_360s")
    f = Formula("C16H32O4")
    print(f.mass)

if __name__ == "__main__":
    main()