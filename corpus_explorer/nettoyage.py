"""Nettoyage du texte extrait des PDF — règles communes et corrections propres à un document."""
import re
import unicodedata

# Coupures de fin de ligne : caractère U+0002 (certains PDF), trait d'union conditionnel, tiret + minuscule
_CESURES = [
    (re.compile(r'\u0002\s*'), ''),
    (re.compile(r'­\s*'), ''),
    (re.compile(r'(?<=[a-zà-ÿ])-\n(?=[a-zà-ÿ])'), ''),
]
_PUCES = re.compile(r'^[•▪●‣⁃◦∙]\s*')
_ESPACES = re.compile(r'[ \t    ]+')


def texte_propre(t: str, remplacements: dict | None = None, ligatures: bool = False) -> str:
    for motif, rempl in _CESURES:
        t = motif.sub(rempl, t)
    t = t.replace('ﬁ', 'fi').replace('ﬂ', 'fl')
    if ligatures:
        # Police mal encodée : « défi nition », « fl ux » → la ligature est suivie d'une espace parasite
        t = re.sub(r'(?<=[A-Za-zÀ-ÿ])(fi|fl|ffi|ff) (?=[a-zà-ÿ])', r'\1', t)
        t = re.sub(r'\b(Fi|Fl|fi|fl) (?=[a-zà-ÿ]{2})', r'\1', t)
    for avant, apres in (remplacements or {}).items():
        t = t.replace(avant, apres)
    t = re.sub(r'\s*\n\s*', ' ', t)
    t = re.sub(r'[\x00-\x08\x0b-\x1f]', '', t)          # caractères de contrôle
    t = _PUCES.sub('• ', t.strip())
    t = re.sub(r'\s+[\uf0b7\u2022]\s+', ' • ', t)
    t = re.sub(r'[\ue000-\uf8ff]\s*', '', t).strip()   # pictogrammes (zone à usage privé)
    return _ESPACES.sub(' ', t).strip()


def est_puce(t: str) -> bool:
    return t.startswith(('• ', '→', '- ', '– '))


def normaliser(t: str) -> str:
    """Forme indexée et cherchée : minuscules, sans accents, ligatures dépliées."""
    t = t.replace('œ', 'oe').replace('Œ', 'oe').replace('æ', 'ae').replace('Æ', 'ae')
    t = unicodedata.normalize('NFKD', t)
    return ''.join(c for c in t if not unicodedata.combining(c)).casefold()


_MOT = re.compile(r"[^\W\d_]{3,}")


def porte_du_sens(t: str) -> bool:
    """Faux passage à écarter, quel que soit l'extracteur : aucun mot de 3 lettres (ligne de formulaire « ____ »,
    lettrine isolée, case « (a) (b) », horaire « 9h00 à 9h30 ») ou seulement des cases « Oui » / « Non »."""
    mots = {m.lower() for m in _MOT.findall(t)}
    return bool(mots - {'oui', 'non'})


# Mots courts légitimes (fr, en, de, es, it) : le reste des mots de 1-2 lettres trahit un texte fragmenté
MOTS_COURTS = set('a à ai as au ce ça ci de du en et il je la le ma me ne on ou où sa se si tu un va y an am at be by '
                  'do go he if in is it my of on or so to up us we da er im ja zu el lo se su al di e o i è ha ho'.split())
ELISIONS = set('l d s c n j m t qu'.split())             # légitimes seulement devant une apostrophe : « l'alerte »


def fragmentation(texte: str) -> float:
    """Part des mots de 1-2 lettres qui ne sont pas des mots courts : « cer ta ines » → élevée (OCR défaillant)."""
    mots = list(re.finditer(r'[^\W\d_]+', texte.lower()))
    if len(mots) < 50:
        return 0.0
    def fragment(m):
        w = m.group()
        if len(w) > 2 or w in MOTS_COURTS:
            return False
        return not (w in ELISIONS and texte[m.end():m.end() + 1] in ("'", '’'))
    return sum(fragment(m) for m in mots) / len(mots)


def mots_suspects(texte: str) -> float:
    """Signes collés aux lettres pour mille mots ; un PDF natif en a presque aucun, un OCR défaillant des dizaines."""
    n = len(re.findall(r'[^\W\d_]+', texte))
    return 1000 * lettres_suspectes(texte) / n if n >= 50 else 0.0


SEUIL_FRAGMENTATION = 0.12      # part de fragments de mots au-delà de laquelle l'OCR est suspect
SEUIL_SUSPECTS = 5.0            # signes collés aux lettres, pour mille mots


def ocr_defaillant(texte: str) -> tuple[bool, float, float]:
    """(suspect ?, part de fragments de mots, signes collés aux lettres pour mille mots)."""
    f, s = fragmentation(texte), mots_suspects(texte)
    return f > SEUIL_FRAGMENTATION or s > SEUIL_SUSPECTS, f, s


def lettres_suspectes(texte: str) -> int:
    """Signes collés aux lettres d'un mot (« m€.-sur€ », « l~a ») : lettres mal reconnues par un OCR."""
    return len(re.findall(r'(?<=[^\W\d_])[€~•@§]|[€~•@§](?=[^\W\d_])', texte))
