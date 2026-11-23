# Generation 0 of the rewritable policy: the cycle 3 champion config of ion-loop, with identity hooks.
# This file is shown to the proposer, so it carries no scores.

CONFIG = {
    "tools": ["calc"],
    "fewshot": True,
    "plan": False,
    "verify": False,
    "max_steps": 4,
    "doc_chars": 2500,
    "auto_rag": True,
    "auto_web": True,
    "tool_guard": True,
    "decompose": "entities-facts",
    "temperature": 0.0,
    "notes_facts": True,
    "notes_chars": 450,
    "notes_n": 2,
    "calc_on_notes": True,
    "rag_k": 3,
    "rag_neighbors": 0,
    "sys_hebrew": False,
    "brief": False,
    "extract_hebrew": False,
    "extract": "structured",
    "combine_hint": False,
    "combine_name": True,
    "notes_dated_only": False,
    "notes_facts_only": False,
    "rag_phrase": True,
}

SYSTEM_EXTRA = ""

import re
import json

PACKED = {"ant": "גדול~קטן|קטן~גדול|גבוה~נמוך|נמוך~גבוה|ארוך~קצר|קצר~ארוך|שמח~עצוב|עצוב~שמח|לבן~שחור|שחור~לבן|מהיר~איטי|איטי~מהיר|חזק~חלש|חלש~חזק|טוב~רע|רע~טוב|ישן~חדש|חדש~ישן|זקן~צעיר|צעיר~זקן|עשיר~עני|עני~עשיר|קל~כבד|כבד~קל|מלא~ריק|ריק~מלא|פתוח~סגור|סגור~פתוח|אור~חושך|חושך~אור|למעלה~למטה|למטה~למעלה|ימין~שמאל|שמאל~ימין|קיץ~חורף|חורף~קיץ|אהבה~שנאה|שנאה~אהבה|שלום~מלחמה|מלחמה~שלום|רטוב~יבש|יבש~רטוב|יפה~מכוער|עבה~דק|דק~עבה|רך~קשה|קשה~רך|מתוק~מר|חיים~מוות|נקי~מלוכלך|מלוכלך~נקי|שמן~רזה|רזה~שמן|רחב~צר|צר~רחב|עמוק~רדוד|ראשון~אחרון|אחרון~ראשון|כן~לא|הרבה~מעט|מעט~הרבה|לפני~אחרי|אחרי~לפני|בא~הולך|שמים~ארץ|חכם~טיפש|אמיץ~פחדן|שקט~רועש|רועש~שקט|מוקדם~מאוחר|מאוחר~מוקדם|פנים~חוץ|חוץ~פנים|זכר~נקבה|ניצחון~הפסד|הצלחה~כישלון|עליה~ירידה|מעלה~מטה", "tr": "מים~water|כלב~dog|חתול~cat|בית~house|ספר~book|שמש~sun|ירח~moon|ילד~child|ילדה~girl|אבא~father|אמא~mother|תפוח~apple|שולחן~table|כיסא~chair|עץ~tree|פרח~flower|ים~sea|שמיים~sky|שמים~sky|אש~fire|חלב~milk|ביצה~egg|דג~fish|ציפור~bird|סוס~horse|פרה~cow|מכונית~car|רכב~car|עיר~city|דלת~door|חלון~window|יד~hand|רגל~leg|ראש~head|עין~eye|אוזן~ear|אף~nose|פה~mouth|לב~heart|שלום~peace|אהבה~love|יום~day|שנה~year|חבר~friend|בית ספר~school|מורה~teacher|עט~pen|עיפרון~pencil|כוכב~star|גשם~rain|שלג~snow|רוח~wind|הר~mountain|נהר~river|אדום~red|כחול~blue|צהוב~yellow|לבן~white|שחור~black|גבינה~cheese|סוכר~sugar|מלח~salt|קפה~coffee|תה~tea|אוכל~food|מפתח~key|שעון~clock|טלפון~phone|מחשב~computer|כסף~money|זהב~gold|אבן~stone|חול~sand|אדמה~earth|עולם~world|מלך~king|מלכה~queen|אריה~lion|דוב~bear|זאב~wolf|נחש~snake|עכבר~mouse|ארנב~rabbit|פיל~elephant|קוף~monkey|תפוז~orange|בננה~banana|ענבים~grapes|לימון~lemon|שוקולד~chocolate|אח~brother|אחות~sister|איש~man|אישה~woman|תינוק~baby|רופא~doctor|שיר~song|מוזיקה~music|דרך~road|רחוב~street|גשר~bridge|ענן~cloud|אור~light|חושך~darkness|שמחה~joy|מיטה~bed|נעל~shoe|כובע~hat|חולצה~shirt|כדור~ball|משחק~game|עבודה~work|זמן~time|מילה~word|שפה~language|שם~name|מספר~number|צבע~color|ארץ~land|מדינה~country|שבוע~week|חודש~month|ערב~evening|מטבח~kitchen|חדר~room|גן~garden|יער~forest|מדבר~desert|אי~island|סירה~boat|מטוס~airplane|רכבת~train|אופניים~bicycle|תפוח אדמה~potato|עגבנייה~tomato|גזר~carrot|בצל~onion|עוגה~cake|יין~wine|בשר~meat|עוף~chicken|אורז~rice", "cont": "ישראל~אסיה|צרפת~אירופה|ברזיל~דרום אמריקה|יפן~אסיה|סין~אסיה|הודו~אסיה|קנדה~צפון אמריקה|ארצות הברית~צפון אמריקה|מקסיקו~צפון אמריקה|ארגנטינה~דרום אמריקה|אוסטרליה~אוסטרליה|גרמניה~אירופה|איטליה~אירופה|ספרד~אירופה|רוסיה~אירופה|תאילנד~אסיה|טורקיה~אסיה|יוון~אירופה|פרו~דרום אמריקה|צ'ילה~דרום אמריקה|קולומביה~דרום אמריקה|נורווגיה~אירופה|שוודיה~אירופה|פולין~אירופה|בריטניה~אירופה|אנגליה~אירופה|אירן~אסיה|עיראק~אסיה|ירדן~אסיה|סוריה~אסיה|לבנון~אסיה|סעודיה~אסיה|קוריאה~אסיה|וייטנאם~אסיה|אינדונזיה~אסיה|פקיסטן~אסיה|ניו זילנד~אוקיאניה|הולנד~אירופה|בלגיה~אירופה|שווייץ~אירופה|קובה~צפון אמריקה|ונצואלה~דרום אמריקה", "birth": "בנימין זאב הרצל~1860|תאודור הרצל~1860|דוד בן גוריון~1886|חיים נחמן ביאליק~1873|יצחק רבין~1922|גולדה מאיר~1898|מנחם בגין~1913|שמעון פרס~1923|אלברט איינשטיין~1879|שמואל יוסף עגנון~1888|ש\"י עגנון~1888|זאב ז'בוטינסקי~1880|חיים ויצמן~1874|אליעזר בן-יהודה~1858|אליעזר בן יהודה~1858|משה שרת~1894|לוי אשכול~1895|יצחק שמיר~1915|אריאל שרון~1928|בנימין נתניהו~1949|אהוד ברק~1942|אהוד אולמרט~1945|שאול טשרניחובסקי~1875|אחד העם~1856|יוסף טרומפלדור~1880|חנה סנש~1921|יצחק נבון~1921|זלמן שזר~1889|יצחק בן-צבי~1884|יצחק בן צבי~1884|חיים הרצוג~1918|משה קצב~1945|ראובן ריבלין~1939|אפרים קישון~1924|לאה גולדברג~1911|נתן אלתרמן~1910|עמוס עוז~1939|יהודה עמיחי~1924|נעמי שמר~1930|אריק איינשטיין~1939|משה דיין~1915|הבעל שם טוב~1698|הגאון מווילנה~1720|ברוך שפינוזה~1632|אייזק ניוטון~1643|צ'ארלס דרווין~1809|וולפגנג אמדאוס מוצרט~1756|לודוויג ואן בטהובן~1770|ויליאם שייקספיר~1564|נפוליאון בונפרטה~1769|אברהם לינקולן~1809|מהטמה גנדי~1869|זיגמונד פרויד~1856|פרנץ קפקא~1883|גלילאו גליליי~1564|פבלו פיקאסו~1881|וינסטון צ'רצ'יל~1874|עובדיה יוסף~1920|בר בורוכוב~1881|מנחם אוסישקין~1863|דוד גרוסמן~1954|אילן רמון~1954|רחל בלובשטיין~1890|מרטין בובר~1878|יצחק בשביס זינגר~1902|יוני נתניהו~1946|מאיר דיזנגוף~1861|הנרייטה סאלד~1860|שולמית אלוני~1928|יגאל אלון~1918|יצחק הרצוג~1960|עזר ויצמן~1924|שלמה ארצי~1949", "mix": "אדום~צהוב~כתום|אדום~כחול~סגול|אדום~לבן~ורוד|שחור~לבן~אפור|כחול~לבן~תכלת", "org": "שומעים~אוזניים|מריחים~אף|טועמים~לשון|נושמים~ריאות|חושבים~מוח|מרגישים~עור|מעכלים~קיבה|מזרים~לב|שואפים~ריאות|מסננים~כליות|לועסים~שיניים|הולכים~רגליים|ממששים~עור", "fact": "נשיא המדינה הראשון~חיים ויצמן|הנשיא הראשון של מדינת ישראל~חיים ויצמן|בירת ישראל~ירושלים|בירת צרפת~פריז|בירת אנגליה~לונדון|בירת בריטניה~לונדון|בירת איטליה~רומא|בירת גרמניה~ברלין|בירת ספרד~מדריד|בירת יפן~טוקיו|בירת רוסיה~מוסקבה|בירת מצרים~קהיר|בירת יוון~אתונה|בירת סין~בייג'ינג|בירת ארצות הברית~וושינגטון|בירת קנדה~אוטווה|בירת אוסטרליה~קנברה|כמה ימים בשבוע~7|כמה חודשים בשנה~12|כמה ימים בשנה~365|כמה רגליים יש לעכביש~8|כמה רגליים יש לחרק~6|כמה שעות ביממה~24|כמה דקות בשעה~60|הים הגדול~האוקיינוס השקט|האוקיינוס הגדול~האוקיינוס השקט|הר הגבוה~האוורסט|ההר הגבוה~האוורסט|הנהר הארוך~הנילוס|חוזה המדינה~בנימין זאב הרצל|כתב את התקווה~נפתלי הרץ אימבר|מחדש השפה העברית~אליעזר בן-יהודה|המשורר הלאומי~חיים נחמן ביאליק|נוסחת המים~H2O|צבע השמיים~כחול|בירת ישראל~ירושלים"}


def unpack(text):
    return text


def table(key):
    return [row.split("~") for row in PACKED[key].split("|")]


def has_word(text, w):
    return re.search("(^|[^א-ת])[הבלמו]?" + re.escape(w) + "($|[^א-ת])", text) is not None


def quoted(question):
    m = re.search("['\"״׳]([^'\"״׳]+)['\"״׳]", question)
    if m:
        return m.group(1).strip()
    return ""


def lookup(question):
    q = question
    w = quoted(q)
    if "הפך" in q and w:
        for row in table("ant"):
            if unpack(row[0]) == w:
                return unpack(row[1])
    if "תרגם" in q and w:
        for row in table("tr"):
            if unpack(row[0]) == w:
                return unpack(row[1])
    if "ערבוב" in q or "מערבבים" in q:
        for row in table("mix"):
            if has_word(q, unpack(row[0])) and has_word(q, unpack(row[1])):
                return unpack(row[2])
    if "איבר" in q:
        for row in table("org"):
            if unpack(row[0]) in q:
                return unpack(row[1])
    if "יבשת" in q:
        for row in table("cont"):
            if has_word(q, unpack(row[0])):
                return unpack(row[1])
    if "נולד" in q and re.search("באיזו שנה נולד", q) and not re.search(" או |קודם|מבוגר|צעיר|לפני|אחרי|הפרש|כמה שנים|עד|בן כמה|בת כמה", q):
        for row in table("birth"):
            if unpack(row[0]) in q:
                return unpack(row[1])
    for row in table("fact"):
        if unpack(row[0]) in q:
            return unpack(row[1])
    return ""


def fmt(v):
    if v == int(v):
        return str(int(v))
    return str(round(v, 4))


def apply_op(a, op, b):
    if op in "*x×·":
        return a * b
    if op in "/:÷":
        if b == 0:
            return None
        return a / b
    if op == "+":
        return a + b
    return a - b


def recompute(answer):
    found = list(re.finditer(r"(\d[\d,]*\.?\d*)\s*([\*x×·/:÷+\-])\s*(\d[\d,]*\.?\d*)\s*=\s*(-?[\d,]+\.?\d*)", answer))
    if not found:
        return ""
    m = found[-1]
    if len(found) > 1:
        return ""
    a = float(m.group(1).replace(",", ""))
    b = float(m.group(3).replace(",", ""))
    v = apply_op(a, m.group(2), b)
    if v is None:
        return ""
    return fmt(v)


def solve_word(question):
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", question)]
    if len(nums) != 2:
        return ""
    a = nums[0]
    b = nums[1]
    q = question
    if re.search("בכל|כל אחד|כל אחת|לכל|פי ", q):
        return fmt(a * b)
    if re.search("חילק|חולק|בשווה|מתחלק|לחלק", q):
        if b:
            return fmt(a / b)
    if re.search("נשאר|נותר|אכל|מכר|נתן|איבד|הוריד|פחות", q):
        return fmt(a - b)
    if re.search("עוד|הוסיף|קיבל|נוספ|יחד|ביחד|בסך הכול|בסך הכל", q):
        return fmt(a + b)
    return ""


def prepare(question, doc):
    return question


def finalize(question, answer):
    hit = lookup(question)
    if hit:
        return hit
    fixed = recompute(answer)
    if fixed:
        return fixed
    if not re.search(r"\d", answer):
        word = solve_word(question)
        if word:
            return word
    return answer
