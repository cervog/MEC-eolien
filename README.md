# Bulletin quotidien du marché électrique français

Ébauche de produit : un mail automatique envoyé chaque jour avec l'état du marché
spot et la disponibilité du parc de production français.

## Contenu du mail

| Section | Contenu | Source ENTSO-E |
|---|---|---|
| Chiffres clés | Spot base J+1 et variation vs J, nucléaire disponible, total indisponible | — |
| Prix spot day-ahead | Base, pointe 8h-20h, min/max horodatés, durée de prix négatifs pour J-1, J, J+1 ; profil horaire J+1 | Day-ahead prices (A44) |
| Disponibilité du parc | Installé / indisponible / disponible / taux par filière pilotable | Unavailability of generation units (A80) + Installed capacity (A68) |
| Nouvelles fortuites | Indisponibilités fortuites en cours déclarées depuis moins de 24 h | A80 |
| Retours sous 7 jours | Unités dont la fin d'indisponibilité est annoncée dans la semaine | A80 |
| Principales indisponibilités | Top 15 des unités indisponibles (MW, type, fin prévue) | A80 |
| Mix de production d'hier | GWh et part par filière | Actual generation per type (A75) |

Les déclarations d'indisponibilité sont dédoublonnées : on garde la dernière révision
de chaque déclaration, on retire les déclarations annulées ou retirées, et une unité
couverte par plusieurs déclarations n'est comptée qu'une fois (la plus pénalisante).

Si une source ne répond pas, le mail part quand même avec les autres sections et
liste les sources en erreur en bas de page.

## Utilisation

```bash
pip install -r requirements.txt

# Aperçu avec des données synthétiques, sans clé d'API
python -m bulletin --demo --out apercu.html

# Données réelles, écrites dans un fichier
ENTSOE_TOKEN=... python -m bulletin --out bulletin.html

# Données réelles + envoi du mail
ENTSOE_TOKEN=... SMTP_HOST=... SMTP_USER=... SMTP_PASSWORD=... MAIL_TO=... python -m bulletin --send

pytest -q
```

### Variables d'environnement

| Variable | Rôle |
|---|---|
| `ENTSOE_TOKEN` | Jeton d'API ENTSO-E (gratuit : créer un compte sur transparency.entsoe.eu puis demander l'accès « Restful API » par mail à transparency@entsoe.eu) |
| `SMTP_HOST`, `SMTP_PORT` | Serveur d'envoi (port 587 STARTTLS par défaut, 465 SSL). Gmail : `smtp.gmail.com` avec un mot de passe d'application |
| `SMTP_USER`, `SMTP_PASSWORD` | Identifiants SMTP |
| `MAIL_FROM` | Expéditeur (par défaut `SMTP_USER`) |
| `MAIL_TO` | Destinataires, séparés par des virgules |

## Envoi automatique

Le workflow `.github/workflows/bulletin.yml` tourne chaque jour à 12h20 UTC
(après la publication des prix J+1), lance les tests, génère le bulletin, l'envoie
et le garde en artefact du run. Il se lance aussi à la main depuis l'onglet
Actions (« Run workflow »). Les variables ci-dessus sont à créer en *secrets* du
dépôt : Settings → Secrets and variables → Actions.

## Structure

```
bulletin/
  sources.py      appels ENTSO-E (entsoe-py), tolérants aux pannes
  indicators.py   calculs (fonctions pures, testées)
  render.py       mise en forme, formats français, objet du mail
  templates/      gabarit HTML du mail (styles en ligne pour les clients mail)
  mailer.py       envoi SMTP
  demo.py         données synthétiques au format entsoe-py
tests/
```

## Pistes pour la suite

- **RTE (API data.rte-france.com)** : prévisions de consommation, production éolienne
  et solaire prévue, signal Ecowatt, éCO2mix temps réel.
- **Historique** : stocker chaque jour les indicateurs (CSV ou base) pour afficher des
  tendances (disponibilité nucléaire sur 30 jours, comparaison avec l'an dernier).
- **Prix à terme** (calendaire, trimestre, mois) : données EEX payantes, ou sources
  publiques en différé.
- **Interconnexions** : solde exportateur et capacités disponibles aux frontières.
- **Alertes** : mail immédiat sur une nouvelle indisponibilité fortuite nucléaire au-delà
  d'un seuil, ou sur des prix négatifs J+1.
