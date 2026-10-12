"""Bulletin quotidien du marché électrique français.

Collecte les prix spot day-ahead, le mix de production et les indisponibilités
du parc français (plateforme de transparence ENTSO-E), calcule quelques
indicateurs et les envoie par mail.
"""

TZ = "Europe/Paris"
