ZONES = ["LC", "LW", "C", "RW", "RC"]

CLASS_ORDER = ["B2","B1","A","2A","3A","4A","5A","6A","N/A"]

_RYG   = [[0,"#d73027"],[0.35,"#fdae61"],[0.65,"#fee08b"],[1,"#1a9850"]]
_RYG_R = [[0,"#1a9850"],[0.35,"#fee08b"],[0.65,"#fdae61"],[1,"#d73027"]]

# Key: (shot_type, zone, is_contested)  — contested = guarded_by_id is not None
SHOT_RATING = {
    (3,"C", False): 0.7,  (3,"C", True):-0.2,
    (3,"RC",False): 0.7,  (3,"RC",True):-0.5,
    (3,"LC",False): 0.7,  (3,"LC",True):-0.5,
    (3,"RW",False): 0.5,  (3,"RW",True):-0.6,
    (3,"LW",False): 0.5,  (3,"LW",True):-0.6,
    (2,"C", False): 1.0,  (2,"C", True):-0.2,
    (2,"RC",False): 0.2,  (2,"RC",True):-0.8,
    (2,"LC",False): 0.2,  (2,"LC",True):-0.8,
    (2,"RW",False): 0.1,  (2,"RW",True):-1.0,
    (2,"LW",False): 0.1,  (2,"LW",True):-1.0,
}

# Estimated FG% by shot location and contest status
EST_FGP = {
    (3,"C", False):0.38, (3,"C", True):0.30,
    (3,"RC",False):0.42, (3,"RC",True):0.33,
    (3,"LC",False):0.42, (3,"LC",True):0.33,
    (3,"RW",False):0.36, (3,"RW",True):0.28,
    (3,"LW",False):0.36, (3,"LW",True):0.28,
    (2,"C", False):0.65, (2,"C", True):0.50,
    (2,"RC",False):0.40, (2,"RC",True):0.30,
    (2,"LC",False):0.40, (2,"LC",True):0.30,
    (2,"RW",False):0.38, (2,"RW",True):0.28,
    (2,"LW",False):0.38, (2,"LW",True):0.28,
}

# Half-court zone bubble positions (x=horizontal ft, y=depth from basket ft).
# Wings pulled closer to the basket; arc radius set to 23 ft for visual scale.
_ZONE_XY = {
    ("C",  2): ( 0,   7),  ("C",  3): ( 0,  23),   # paint / top-of-key
    ("LC", 2): (-14,  5),  ("LC", 3): (-21,  9),   # left corner
    ("LW", 2): (-13, 11),  ("LW", 3): (-18, 15),   # left wing
    ("RW", 2): ( 13, 11),  ("RW", 3): ( 18, 15),   # right wing
    ("RC", 2): ( 14,  5),  ("RC", 3): ( 21,  9),   # right corner
}
