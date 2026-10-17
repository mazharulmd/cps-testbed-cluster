#!/bin/sh
# Compiles the TikZ diagrams in diagrams/ to individual PDF figures in ../figures/.
set -e
cd "$(dirname "$0")/diagrams"
for f in fig_*.tex; do
  pdflatex -interaction=nonstopmode -halt-on-error "$f" >/dev/null
  mv "${f%.tex}.pdf" ../../figures/
done
rm -f *.aux *.log
