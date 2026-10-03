#!/usr/bin/env python3
"""Capture d'une page de corpus-explorer avec un navigateur sans interface, et relevé des erreurs JavaScript.

Usage : python3 capturer.py <adresse> <image.png> [--largeur 1400] [--hauteur 900] [--entiere] [--attendre 3000]
Exemple : python3 capturer.py http://localhost:8766/projets/demo/carte /tmp/carte.png --attendre 6000

Prérequis : Playwright pour le Python système (pip install --user playwright) et Google Chrome installé.
Sortie : l'image, puis la liste des erreurs JavaScript et des requêtes en échec (code ≥ 400) ; code de sortie 1 s'il
y en a.
"""
import argparse
import sys

from playwright.sync_api import sync_playwright


def main():
    a = argparse.ArgumentParser()
    a.add_argument('adresse')
    a.add_argument('image')
    a.add_argument('--largeur', type=int, default=1400)
    a.add_argument('--hauteur', type=int, default=900)
    a.add_argument('--entiere', action='store_true', help='toute la hauteur de la page')
    a.add_argument('--attendre', type=int, default=3000, help='millisecondes après le chargement (rendu, appels API)')
    o = a.parse_args()
    erreurs, echecs = [], []
    with sync_playwright() as pw:
        b = pw.chromium.launch(executable_path='/usr/bin/google-chrome', headless=True)
        page = b.new_page(viewport={'width': o.largeur, 'height': o.hauteur})
        page.on('pageerror', lambda e: erreurs.append(str(e)))
        page.on('console', lambda m: erreurs.append(f"{m.text} ({m.location.get('url', '')})")
                if m.type == 'error' else None)
        page.on('response', lambda r: echecs.append(f'{r.status} {r.url}') if r.status >= 400 else None)
        page.goto(o.adresse, wait_until='networkidle')
        page.wait_for_timeout(o.attendre)
        page.screenshot(path=o.image, full_page=o.entiere)
        b.close()
    print(f'→ {o.image}')
    for e in erreurs:
        print(f'  erreur JavaScript : {e}')
    for e in echecs:
        print(f'  requête en échec : {e}')
    sys.exit(1 if erreurs or echecs else 0)


if __name__ == '__main__':
    main()
