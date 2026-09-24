"""Une seule grammaire de couleurs pour les boutons.

Un même geste recevait des couleurs différentes selon la page : « Envoyer »
était vert dans le formulaire de réservation et bleu dans celui d'un véhicule,
« Nouvel utilisateur » vert alors que « Nouveau véhicule » était bleu. Le vert
servait en plus d'état (réservation approuvée), si bien qu'il voulait dire deux
choses à la fois.

La convention retenue est décrite en tête de ``static/custom.css``. Ces tests
ne jugent pas du goût : ils constatent qu'elle n'a pas été perdue.
"""

import pathlib
import re

import pytest

GABARITS = sorted(pathlib.Path("templates").glob("*.html"))
CSS = pathlib.Path("static/custom.css").read_text(encoding="utf-8")


def _classes(fichier):
    """Toutes les listes de classes de boutons d'un gabarit."""
    texte = fichier.read_text(encoding="utf-8")
    return re.findall(r'class="([^"]*\bbtn\b[^"]*)"', texte)


@pytest.mark.parametrize("fichier", GABARITS, ids=lambda f: f.name)
def test_no_solid_green_or_grey_buttons(fichier):
    """Le vert et le gris pleins ont disparu des boutons.

    Le vert redevient une couleur d'état (badge « approuvée », véhicule
    disponible) ; le gris plein faisait peser « Annuler » autant
    qu'« Enregistrer ».
    """
    for classes in _classes(fichier):
        mots = classes.split()
        assert "btn-success" not in mots, f"{fichier.name} : vert plein, réservé aux états"
        assert "btn-secondary" not in mots, f"{fichier.name} : gris plein, utiliser le contour"


@pytest.mark.parametrize("nom,libelle", [
    # Chercher est un outil : le bleu plein revient à « Nouvel utilisateur ».
    ("admin_users.html", "Chercher"),
    # Segmenter une journée est une opération annexe, sous « Approuver ».
    ("manage_request.html", "Attribuer ce véhicule"),
])
def test_secondary_actions_do_not_compete(nom, libelle):
    """Deux boutons bleus pleins sur un écran ne désignent plus rien.

    Le comptage n'est volontairement pas automatique : plusieurs gabarits
    portent deux boutons dans deux branches ``{% if %}`` dont une seule
    s'affiche, et un test naïf les signalerait à tort.
    """
    for ligne in (pathlib.Path("templates") / nom).read_text(encoding="utf-8").splitlines():
        if libelle in ligne and "btn" in ligne:
            assert "btn-outline" in ligne, ligne.strip()
            return
    # Le libellé peut être sur la ligne suivante : on remonte au bouton.
    texte = (pathlib.Path("templates") / nom).read_text(encoding="utf-8")
    avant = texte.split(libelle)[0]
    assert "btn-outline" in avant.rsplit("<button", 1)[-1], f"{nom} : {libelle}"


def test_cancel_links_are_outlined():
    """« Annuler » posé à côté d'« Enregistrer » s'efface.

    Seuls les liens sont concernés : ailleurs, « Annuler » désigne l'annulation
    d'une réservation, qui est destructive et reste en rouge.
    """
    vus = 0
    for fichier in GABARITS:
        for lien in re.findall(r"<a\b[^>]*>\s*Annuler\s*</a>",
                               fichier.read_text(encoding="utf-8")):
            vus += 1
            assert "btn-outline-secondary" in lien, f"{fichier.name} : {lien}"
    assert vus >= 3, "les liens « Annuler » des formulaires ont disparu"


def test_list_rows_use_outlined_actions():
    """Cinquante lignes de tableau affichaient cinquante boutons bleus pleins."""
    texte = (pathlib.Path("templates") / "admin_reservations.html").read_text(encoding="utf-8")
    gerer = [l for l in texte.splitlines() if "manage_request" in l and "btn" in l]
    assert gerer, "les boutons « Gérer » ont disparu"
    for ligne in gerer:
        assert "btn-outline-primary" in ligne, ligne.strip()


def test_repeated_deletions_are_outlined():
    """Une ligne par véhicule, donc un rouge plein par ligne : la page en
    était saturée."""
    texte = (pathlib.Path("templates") / "admin_vehicles.html").read_text(encoding="utf-8")
    supprimer = [l for l in texte.splitlines() if ">Supprimer<" in l]
    assert supprimer, "le bouton « Supprimer » a disparu"
    for ligne in supprimer:
        assert "btn-outline-danger" in ligne, ligne.strip()


def test_convention_is_written_down():
    """Sans trace écrite, la règle se reperd à la première retouche."""
    assert "CONVENTION DES BOUTONS" in CSS
    for classe in ("btn-primary", "btn-outline-primary", "btn-outline-secondary",
                   "btn-danger", "btn-outline-danger", "btn-outline-success",
                   "btn-outline-warning"):
        assert classe in CSS.split("CONVENTION DES BOUTONS")[1][:1500], classe


def test_dashboard_icons_share_one_colour():
    """Six tuiles de six couleurs faisaient un arc-en-ciel ; la forme de
    l'icône suffit à distinguer les sections."""
    assert ".dashboard-icon.icon-" not in CSS, "teinte par section résiduelle"
    for gabarit in ("user_home.html", "admin_home.html", "superadmin_home.html"):
        texte = (pathlib.Path("templates") / gabarit).read_text(encoding="utf-8")
        assert "dashboard-icon icon-" not in texte, gabarit
    # ``\n.dashboard-icon`` : sinon on attrape la règle de survol, qui se
    # termine par le même texte.
    bloc = CSS.split("\n.dashboard-icon {")[1].split("}")[0]
    assert "color: var(--color-primary)" in bloc
    assert "background: var(--color-primary-light)" in bloc


def test_dashboard_icon_stays_round_on_phones():
    petit = CSS.split("@media (max-width: 768px)")[1]
    bloc = petit.split("\n  .dashboard-icon {")[1].split("}")[0]
    largeur = re.search(r"width: ([\d.]+)rem", bloc)
    hauteur = re.search(r"height: ([\d.]+)rem", bloc)
    assert largeur and hauteur, "une pastille sans hauteur s'allonge en ovale"
    assert largeur.group(1) == hauteur.group(1)


# --- lisibilité ---------------------------------------------------------------

def _luminance(hexa):
    hexa = hexa.lstrip("#")
    def canal(paire):
        v = int(paire, 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, v, b = canal(hexa[0:2]), canal(hexa[2:4]), canal(hexa[4:6])
    return 0.2126 * r + 0.7152 * v + 0.0722 * b


def _contraste(a, b):
    clair, sombre = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (clair + 0.05) / (sombre + 0.05)


def _variable(nom, theme=":root"):
    """Valeur déclarée d'une variable CSS, dans le thème demandé."""
    bloc = CSS.split(theme + " {", 1)[1].split("}", 1)[0]
    for ligne in bloc.splitlines():
        if ligne.strip().startswith(nom + ":"):
            return ligne.split(":", 1)[1].strip().rstrip(";")
    raise AssertionError(f"{nom} absente de {theme}")


SEUIL = 4.5  # texte courant lisible, norme WCAG AA
FOND_CLAIR = "#ffffff"
FOND_SOMBRE = "#0f172a"


@pytest.mark.parametrize("variable", ["--btn-success-text", "--btn-warning-text",
                                      "--btn-danger-text", "--color-primary"])
def test_outline_button_text_is_legible(variable):
    """Mesuré avant correction : 1,95 sur « Indisponibilités », 3,71 sur
    « Gérer ». L'application se consulte dehors, parfois avec des gants."""
    clair = _contraste(_variable(variable), FOND_CLAIR)
    sombre = _contraste(_variable(variable, '[data-theme="dark"]'), FOND_SOMBRE)
    assert clair >= SEUIL, f"{variable} sur fond clair : {clair:.2f}"
    assert sombre >= SEUIL, f"{variable} sur fond sombre : {sombre:.2f}"


@pytest.mark.parametrize("variable", ["--btn-success-fill", "--btn-warning-fill",
                                      "--btn-danger-fill"])
def test_filled_button_keeps_white_text_legible(variable):
    """Au survol le bouton se remplit : le blanc doit y rester lisible."""
    mesure = _contraste(_variable(variable), "#ffffff")
    assert mesure >= SEUIL, f"{variable} : {mesure:.2f}"


def test_dark_mode_primary_button_is_not_washed_out():
    """L'accent s'éclaircit en mode sombre pour le texte ; du blanc posé
    dessus retombait à 3,7."""
    bloc = CSS.split('[data-theme="dark"] .btn-primary {')[1].split("}")[0]
    couleur = bloc.split("background-color:")[1].split(";")[0].strip()
    assert _contraste(couleur, "#ffffff") >= SEUIL, couleur


def test_button_inside_an_alert_stays_legible():
    """Mesuré à 1,22 de contraste : un bouton posé dans une alerte héritait
    d'un texte blanc sur fond pâle. Fond franc et texte sombre, quelle que soit
    la couleur de l'alerte."""
    bloc = CSS.split(".alert .btn-outline-secondary {")[1].split("}")[0]
    assert "background: var(--color-background)" in bloc
    assert "color: var(--color-text)" in bloc
    # Texte sombre sur fond blanc : très au-dessus du seuil.
    assert _contraste("#1e293b", "#ffffff") >= SEUIL
