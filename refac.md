Le refactoring demandé est faisable sans réécrire tout HTAS, à condition de le traiter comme une fermeture de contrat plutôt qu'une refonte métier complète.

- **Faisable immédiatement**
  - figer la surface contractuelle à `configure`, `load`, `describe`, `extract`, `transform`, `render`, `export`
  - introduire des requêtes typées publiques dans `ht/api_types.py`
  - convertir `describe` en catalogue unique côté frontend
  - reclasser `register_compartment` et les helpers `build_*` / `compute_*` / `render_*` en compatibilité temporaire avec avertissement de dépréciation
  - aligner la documentation, les types publics et la façade

- **Point structurant traité ici**
  - pour `load`, le contrat public de géométrie passe par un **provider public** (`geometry_source.kind == "provider"`), ce qui évite toute dépendance QGIS dans le coeur de HTAS tout en laissant CWV fournir son mode de construction actuel

- **Limites restantes**
  - certains workflows métier restent implémentés par délégation aux helpers existants ; ils sont désormais pilotés par des requêtes macro mais pas encore extraits dans des services dédiés
  - un futur incrément pourra remplacer le provider par des sources totalement sérialisables si CWV en a besoin

- **Conclusion**
  - oui, le refactoring est réaliste et peut être livré par petites touches sûres :
    1. fermer le contrat public,
    2. introduire le langage de requêtes,
    3. déplacer les anciens helpers en mode compatibilité,
    4. laisser l'industrialisation interne pour une étape suivante.
