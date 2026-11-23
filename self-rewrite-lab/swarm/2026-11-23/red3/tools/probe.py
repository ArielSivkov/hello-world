import sys,json; sys.path[:0]=["/home/user/swarm/red3/lab/ion-loop","/home/user/swarm/red3/lab"]
from arena.run import load
from rewrite.evaluate import others_by_kind, grade
pool=others_by_kind(); dev={t["id"]:t for t in load("dev")}
tests=[("basic-005","טוקיו, סיאול, בנגקוק"),("basic-005","לא טוקיו"),("basic-005","בטוח שלא טוקיו"),
("basic-005","סיאול, ואולי טוקיו"),("basic-005","סיאול - טוקיו - בנגקוק"),("basic-005","סיאול וגם טוקיו"),
("basic-005","סיאול\tטוקיו"),("basic-005","סיאול, טוקיו"),("basic-005","סיאול and tokyo"),("basic-005","Seoul, Tokyo, Bangkok"),
("basic-001","ברלין, פריז"),("basic-001","מינכן, ברלין, המבורג"),
("web-032","1888, 1890"),("web-032","1890 (או 1891)"),("web-032","1891? לא, 1890"),("web-032","בין 1885 ל-1895: 1890"),
("web-032","1889–1890"),("web-032","1890 ± 2"),("web-032","1890s"),("web-032","שנת 1890 בערך, אולי 1891, 1889... 1890"),
("multistep-052","אברהם שלונסקי, לא זלדה"),("multistep-052","זלדה? אברהם שלונסקי"),
("longdoc-064","CR-6908, CR-6909"),("longdoc-067","מגש מעור, מגש מאבן"),("longdoc-067","מגש מעור, קערה מעור"),
("calc-020","43766632 ± 1"),("calc-020","43766631, 43766632"),("multistep-060","8"),("multistep-060","8 שנים, או 18"),
("basic-003","8, שבעה"),("basic-003","שמונה, שבעה"),("basic-003","בערך שבעה, אולי שמונה"),
("longdoc-065","מדף 59, 60"),("longdoc-069","מדף 1"),("longdoc-069","קומה 2 מדף 1"),("longdoc-069","10, 1"),
]
for i,a in tests:
    print(grade(dev[i],a,"dev",pool), i, repr(a))
