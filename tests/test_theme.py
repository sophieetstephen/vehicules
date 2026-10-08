"""Mode sombre : le texte doit rester lisible sur toutes les pages.

Signalé en test : au passage en mode sombre, des fenêtres et formulaires
devenaient illisibles. L'application ne changeait que ses propres couleurs ;
celles de Bootstrap (texte de base, tableaux, aides des formulaires) restaient
celles du mode clair, gris foncé ou noir sur fond sombre. Mesuré page par
page : jusqu'à 1,18 de contraste, pour 4,5 attendus.
"""

import pathlib
import re

TEMPLATES = pathlib.Path("templates")
CSS = pathlib.Path("static/custom.css").read_text(encoding="utf-8")


def _bloc_sombre():
    debut = CSS.index('[data-theme="dark"] {')
    return CSS[debut:CSS.index("}", debut)]


def test_pages_turn_on_bootstrap_dark_mode_too():
    """Le mode sombre de Bootstrap s'active avec data-bs-theme, en même
    temps que celui de l'application, au chargement comme à la bascule."""
    for nom in ("base.html", "login.html"):
        texte = (TEMPLATES / nom).read_text(encoding="utf-8")
        assert "setAttribute('data-bs-theme', 'dark')" in texte, nom
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "removeAttribute('data-bs-theme')" in base, "retour au mode clair"


def test_theme_is_applied_before_the_page_is_drawn():
    """En fin de page, le thème laissait voir un éclair clair à chaque
    chargement."""
    for nom in ("base.html", "login.html"):
        texte = (TEMPLATES / nom).read_text(encoding="utf-8")
        tete = texte[:texte.index("</head>")]
        assert "setAttribute('data-theme', 'dark')" in tete, nom


def test_bootstrap_colours_follow_the_dark_palette():
    bloc = _bloc_sombre()
    for variable in ("--bs-body-color", "--bs-body-bg", "--bs-emphasis-color",
                     "--bs-secondary-color", "--bs-heading-color", "--bs-border-color"):
        assert re.search(rf"{variable}\s*:", bloc), f"{variable} absente du mode sombre"
    assert "color-scheme: dark" in bloc, "calendriers et listes natifs restaient clairs"


# --- menu « … » des utilisateurs sur téléphone ----------------------------------
#
# Signalé en test : sur téléphone, le menu « … » ne s'ouvrait que pour son
# propre compte. La carte coupait ce qui dépassait (overflow: hidden) : un
# menu d'un seul choix tenait dans la carte, celui des autres comptes (quatre
# choix) restait invisible. Constaté dans un navigateur au format téléphone.

def _regle(css, selecteur):
    debut = css.index(selecteur + " {")
    return css[debut:css.index("}", debut)]


def test_user_card_does_not_clip_its_menu():
    page = (TEMPLATES / "admin_users.html").read_text(encoding="utf-8")
    assert "overflow" not in _regle(page, ".user-card-mobile")


def test_phone_menus_are_positioned_on_the_screen():
    """Comme ceux du tableau : rien autour ne peut les couper."""
    page = (TEMPLATES / "admin_users.html").read_text(encoding="utf-8")
    assert '.user-card-actions [data-bs-toggle="dropdown"]' in page
    assert "strategy: 'fixed'" in page
