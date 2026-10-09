"""Build the Overleaf package: main.tex, references.bib, tables/ and Figures/Fig1..FigN.

Usage: python make_overleaf.py OUT_DIR
Run after main.tex has been compiled (the figure numbers are read from main.aux).
Each figure file is copied as Fig<number>.<ext> in the order the figures appear in the
PDF, and the copy of main.tex points to the new names.
"""
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.join(HERE, "..")
OUT = os.path.join(sys.argv[1], "CPS_Testbed_Paper")

tex = open(os.path.join(PAPER, "main.tex")).read()
aux = open(os.path.join(PAPER, "main.aux")).read()
number = {m.group(1): int(m.group(2)) for m in re.finditer(r"\\newlabel\{(fig:[^}]+)\}\{\{(\d+)\}", aux)}

# figure environments: the file each one includes and its label
files = {}
for env in re.finditer(r"\\begin\{figure\*?\}(.*?)\\end\{figure\*?\}", tex, flags=re.S):
    body = env.group(1)
    inc = re.search(r"\\includegraphics(\[[^]]*\])?\{([^}]+)\}", body)
    lab = re.search(r"\\label\{(fig:[^}]+)\}", body)
    if inc and lab:
        files[inc.group(2)] = number[lab.group(1)]
if len(set(files.values())) != len(files):
    sys.exit("two figures share a number; compile main.tex first")

shutil.rmtree(OUT, ignore_errors=True)
os.makedirs(os.path.join(OUT, "Figures"))
shutil.copytree(os.path.join(PAPER, "tables"), os.path.join(OUT, "tables"),
                ignore=shutil.ignore_patterns("*.txt"))
shutil.copy(os.path.join(PAPER, "references.bib"), OUT)
for src, n in sorted(files.items(), key=lambda x: x[1]):
    new = f"Fig{n}{os.path.splitext(src)[1]}"
    shutil.copy(os.path.join(PAPER, "figures", src), os.path.join(OUT, "Figures", new))
    tex = re.sub(r"(\\includegraphics(\[[^]]*\])?\{)" + re.escape(src) + r"\}", lambda m: m.group(1) + new + "}", tex)
    print(f"{new:10s} <- {src}")
tex = re.sub(r"\\graphicspath\{.*\}", r"\\graphicspath{{Figures/}}", tex)
with open(os.path.join(OUT, "main.tex"), "w") as f:
    f.write(tex)
with open(os.path.join(OUT, "README.txt"), "w") as f:
    f.write("Overleaf upload\n---------------\n"
            "1. New Project > Upload Project > choose CPS_Testbed_Paper.zip.\n"
            "2. Main document: main.tex. Compiler: pdfLaTeX (Menu > Settings).\n"
            "3. Figures/  Fig1 ... Fig%d, numbered as in the paper\n"
            "   tables/   result tables included by main.tex\n"
            "   references.bib  bibliography (IEEEtran style, BibTeX)\n" % len(files))
