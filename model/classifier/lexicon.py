import re
from typing import List, Dict, Pattern, Set
from .normalizer import TextNormalizer


class IntentLexicon:
    """
    Multilingual intent vocabulary & regex patterns covering:
    - English
    - Hindi (Devanagari & Romanized/Hinglish)
    - Marathi (Devanagari & Romanized/Marathish)
    - Code-switching, Romanized transliterations, and ASR variations
    """

    # -------------------------------------------------------------
    # 1. Hard Opt-Out / Do-Not-Contact (Hard Negative, Opt-Out Flag)
    # -------------------------------------------------------------
    OPT_OUT_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(?:don'?t|do\s+not|never)\s+(?:call|contact|reach|message|disturb)\s+(?:me|us)?\s*(?:again|anymore|ever)?\b",
            r"\b(?:stop|quit)\s+(?:calling|contacting|messaging|disturbing|bothering)\b",
            r"\b(?:remove|delete|erase)\s+(?:my|this)?\s*(?:number|contact|data|details)\b",
            r"\b(?:put\s+me\s+on\s+(?:the\s+)?(?:do\s+not\s+call|dnc))\b",
            r"\b(?:block\s+(?:my|this)?\s*number)\b",
            r"\bi\s+don'?t\s+want\s+(?:any\s+more|further)\s+calls\b",
            r"\bdo\s+not\s+disturb\b",
            # Hindi / Hinglish
            r"\b(?:call|phone)\s+(?:mat\s+(?:karna|karo|kijiye|kariyega)|nahi\s+karna)\b",
            r"\b(?:dobara|phir\s*se|bar\s*bar|aage\s*se)\s+(?:call|phone)\s+mat\b",
            r"\b(?:number\s+(?:hata|delete|nikal|remove)\s+(?:do|karo|kijiye|kardo))\b",
            r"\b(?:disturb|pareshan|tang)\s+mat\s+karo\b",
            r"\b(?:bar\s*bar\s+phone\s+mat\s+karo)\b",
            r"\baage\s+se\s+phone\s+mat\s+karna\b",
            # Marathi
            r"\b(?:punha|parat|aata)\s+(?:phone|call)\s+(?:karu\s+naka|nako\s+karu|karu\s+nakos)\b",
            r"\b(?:phone|call)\s+nako\s+karu\b",
            r"\b(?:number\s+(?:kadhun\s+taka|delete\s+kara|kadha))\b",
            r"\b(?:tras|pareshan)\s+deu\s+naka\b",
            r"\byapudhe\s+(?:call|phone)\s+karu\s+naka\b",
            # Devanagari
            r"(?:कॉल|फोन)\s+करू\s+नका",
            r"(?:कॉल|फोन)\s+नको\s+करू",
            r"(?:कॉल|फोन)\s+मत\s+(?:करो|करना|कीजिए)",
            r"दोबारा\s+(?:कॉल|फोन)\s+मत",
            r"नंबर\s+(?:हटा|डिलीट|काढून)\s+(?:कर|दो|टाका)",
            r"यापुढे\s+(?:कॉल|फोन)\s+करू\s+नका",
            r"त्रास\s+देऊ\s+नका",
            r"परेशान\s+मत\s+करो",
            r"कृपया\s+मला\s+पुन्हा\s+फोन\s+करू\s+नका",
            r"कृपया\s+मुझे\s+दोबारा\s+फोन\s+मत\s+कीजिए",
            r"माझा\s+नंबर\s+यादीतून\s+काढून\s+टाका",
            r"मेरा\s+नंबर\s+अपनी\s+लिस्ट\s+से\s+हटा\s+दीजिए",
        ]
    ]

    # -------------------------------------------------------------
    # 2. Wrong Person / Irrelevant Customer (Hard Negative)
    # -------------------------------------------------------------
    WRONG_PERSON_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\bwrong\s+number\b",
            r"\byou\s+have\s+(?:the\s+)?wrong\s+(?:person|number|contact)\b",
            r"\bi'?m\s+not\s+the\s+person\s+you'?re\s+looking\s+for\b",
            r"\bi\s+don'?t\s+(?:use|have|need)\s+this\s+type\s+of\s+service\b",
            r"\bi\s+(?:am\s+not|m\s+not)\s+involved\s+in\s+this\b",
            r"\bi\s+don'?t\s+have\s+this\s+requirement\b",
            r"\bnot\s+for\s+me\b",
            r"\bnot\s+relevant\s+to\s+me\b",
            # Hindi / Hinglish
            r"\b(?:galat|wrong)\s+number\b",
            r"\bkisi\s+aur\s+ka\s+number\b",
            r"\bmain\s+(?:vo|woh|ye)\s+nahi\s+hoon\b",
            r"\bmera\s+(?:isse|ye)\s+koi\s+lena\s*dena\s+nahi\b",
            r"\bmain\s+use\s+nahi\s+karta\b",
            # Marathi
            r"\bchuki\s*cha\s+number\b",
            r"\bmajha\s+he\s+kaam\s+nahi\b",
            r"\bchukun\s+lagla\b",
            # Devanagari
            r"गलत\s+नंबर",
            r"चुकीचा\s+नंबर",
            r"हे\s+माझे\s+काम\s+नाही",
        ]
    ]

    # -------------------------------------------------------------
    # 3. Direct & Explicit Rejections (Negative Signal)
    # -------------------------------------------------------------
    EXPLICIT_REJECTION_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(?:i\s+am\s+not|i'?m\s+not|not)\s+interested\b",
            r"\b(?:i\s+don'?t|do\s+not)\s+(?:need|want)\s+(?:it|this|your\s+service|the\s+service|anything|this\s+product)\b",
            r"\b(?:i\s+don'?t|do\s+not)\s+want\s+to\s+buy\b",
            r"\bi'?m\s+not\s+going\s+to\s+buy\b",
            r"\bthis\s+isn'?t\s+useful\s+to\s+me\b",
            r"\bi\s+already\s+have\s+(?:everything|another|all|one|a\s+similar\s+product)\b",
            r"\bi\s+don'?t\s+want\s+to\s+change\s+providers?\b",
            r"\bnot\s+useful\s+for\s+me\b",
            r"\bnot\s+looking\s+for\s+this\b",
            r"\bi\s+have\s+no\s+interest\b",
            r"\bdefinitely\s+not\b",
            r"\bnever\s+interested\b",
            r"\bno\s+need\b",
            r"\bkeep\s+your\s+service\b",
            r"\b(?:ok\s*,?\s*)?bye(?:\s+bye)?\b",
            r"\bleave\s+it\b",
            r"\bdrop\s+it\b",
            # Hindi / Hinglish
            r"\b(?:nahi|na|nahin)\s*(?:,\s*|\s+)?(?:mujhe\s+)?(?:iski|ye|yeh|is)\s+(?:zarurat|jarurat|jaroorat)\s+nahi\s+hai\b",
            r"\b(?:zarurat|jarurat|jaroorat)\s+nahi\s+hai\b",
            r"\b(?:nahi|na|nahin)\s+chahiye\b",
            r"\bchahiye\s+nahi\b",
            r"\binterest\s+nahi\s+hai\b",
            r"\bkoi\s+(?:interest|shauk|zarurat)\s+nahi\s+hai\b",
            r"\bbilkul\s+(?:bhi\s+)?nahi\b",
            r"\bnahi\s+lena\s+hai\b",
            r"\bnahi\s+lena\b",
            r"\bnahi\s+karna\s+hai\b",
            r"\bmera\s+koi\s+mood\s+nahi\s+hai\b",
            r"\bkaam\s+ka\s+nahi\s+hai\b",
            r"\b(?:kuch\s+)?mat\s+(?:de|do|bhejo|batao|karo|dijiye)\b",
            r"\bicon\s+mat\s+de\b",
            r"\bmat\s+de\b",
            r"\bmat\s+do\b",
            r"\bphone\s+(?:rakh|rakho|kaat|kaato|band\s+karo)\b",
            r"\bkaat\s+do\b",
            r"\bbakwas\b",
            r"\bfaltu\b",
            r"\btime\s+waste\b",
            r"\bmain\s+(?:ise\s+)?nahi\s+khareedna\s+chahta\b",
            r"\bmain\s+(?:ise\s+)?nahi\s+khareedna\s+chahti\b",
            r"\bis\s+offer\s+me\s+dilchaspi\s+nahi\s+hai\b",
            r"\b(?:nahi|na|nahin)\s+(?:janna|chahiye|lena|sunna)\b",
            r"\b(?:mujhe\s+)?(?:nahi\s+janna|nahi\s+chahiye)\b",
            # Marathi
            r"\b(?:mala\s+)?nako\s+(?:aahe|ahe|ye)?\b",
            r"\bnako\s+re\s+baba\b",
            r"\bnakoy\b",
            r"\bnakos\b",
            r"\bgaraj\s+nahi\b",
            r"\bkahi\s+garaj\s+nahi\b",
            r"\binterest\s+nahi\s+mala\b",
            r"\bmala\s+interest\s+nahi\b",
            r"\bkahi\s+upayog\s+nahi\b",
            r"\bphone\s+theva\b",
            r"\bdeu\s+naka\b",
            r"\bpathvu\s+naka\b",
            r"\bmala\s+yat\s+ras\s+nahi\b",
            r"\bmala\s+he\s+ghyayche\s+nahi\b",
            r"\bmala\s+he\s+kharedi\s+karayche\s+nahi\b",
            r"\bmala\s+ha\s+offer\s+nako\b",
            r"\bmala\s+yat\s+ajibaat\s+ras\s+nahi\b",
            r"\bhe\s+majhya\s+upyogache\s+nahi\b",
            # Devanagari (Hindi & Marathi)
            r"गरज\s+नाही",
            r"नको\s+आहे",
            r"नकोय",
            r"नको",
            r"मला\s+नको",
            r"मला\s+यात\s+रस\s+नाही",
            r"मला\s+हे\s+घ्यायचे\s+नाही",
            r"मला\s+हे\s+खरेदी\s+करायचे\s+नाही",
            r"मला\s+हा\s+ऑफर\s+नको",
            r"हे\s+माझ्या\s+उपयोगाचे\s+नाही",
            r"मला\s+यात\s+अजिबात\s+रस\s+नाही",
            r"नाही\s+पाहिजे",
            r"नाही\s+नको",
            r"इन्टरेस्ट\s+नाही",
            r"देऊ\s+नका",
            r"पाठवू\s+नका",
            r"फोन\s+ठेवा",
            r"ज़रूरत\s+नहीं",
            r"जरूरत\s+नहीं",
            r"नहीं\s+चाहिए",
            r"नहीं\s+जानना",
            r"नहीं\s+जाननी",
            r"नहीं\s+सुनना",
            r"नहीं\s+लेना",
            r"नहीं\s+करना",
            r"मुझे\s+इसमें\s+रुचि\s+नहीं\s+है",
            r"मुझे\s+यह\s+नहीं\s+चाहिए",
            r"मुझे\s+इसकी\s+जरूरत\s+नहीं\s+है",
            r"मैं\s+इसे\s+नहीं\s+खरीदना\s+चाहता",
            r"मैं\s+इसे\s+नहीं\s+खरीदना\s+चाहती",
            r"मुझे\s+इस\s+ऑफर\s+में\s+दिलचस्पी\s+नहीं\s+है",
            r"मुझे\s+इसकी\s+जानकारी\s+नहीं\s+चाहिए",
            r"फोन\s+रखो",
            r"काटो",
            r"बंद\s+करो",
            r"बस",
            r"कुछ\s+नहीं\s+चाहिए",
            r"^(?:nahi|nahin|na|no|nope|नाही|ना|नहीं|नको)[\s\.,!]*$",
        ]
    ]

    # -------------------------------------------------------------
    # 4. Indirect & Polite Rejections (Negative Signal)
    # -------------------------------------------------------------
    INDIRECT_REJECTION_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(?:no|nope)\s*,?\s*thanks?\b",
            r"\bno\s+thank\s+you\b",
            r"\bmaybe\s+another\s+time\b",
            r"\bsome\s+other\s+time\b",
            r"\bi'?m\s+happy\s+with\s+(?:my\s+)?current\b",
            r"\bi\s+don'?t\s+need\s+anything\s+right\s+now\b",
            r"\bnot\s+looking\s+right\s+now\b",
            # Hindi / Hinglish
            r"\brehne\s+(?:do|dijiye)\b",
            r"\brahne\s+(?:do|dijiye)\b",
            r"\bchhoro\b",
            r"\bchhod\s+do\b",
            r"\babhi\s+kuch\s+nahi\s+chahiye\b",
            r"\bpehle\s+se\s+hai\b",
            # Marathi
            r"\brahu\s+dya\b",
            r"\baata\s+kahi\s+nako\b",
            r"\baadhich\s+ahe\b",
            # Devanagari
            r"रहने\s+दीजिए",
            r"राहू\s+द्या",
            r"आता\s+काही\s+नको",
            r"अजून\s+काही\s+नको",
            r"छोड़ो",
            r"नहीं\s+धन्यवाद",
        ]
    ]

    # -------------------------------------------------------------
    # 5. Negation Nuances & Scoping Patterns
    # -------------------------------------------------------------
    UNCERTAIN_NEGATION_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\bi'?m\s+not\s+sure\s+if\s+i'?m\s+interested\b",
            r"\bnot\s+sure\s+if\s+interested\b",
            r"\bnot\s+sure\s+whether\b",
            r"मला\s+रस\s+आहे\s+की\s+नाही\s+ते\s+माहीत\s+नाही",
            r"\bmala\s+interest\s+aahe\s+ki\s+nahi\s+te\s+mahit\s+nahi\b",
            r"\bmala\s+ras\s+aahe\s+ki\s+nahi\b",
            r"\bmujhe\s+interest\s+hai\s+ya\s+nahi\s+pata\s+nahi\b",
            r"मुझे\s+रुचि\s+है\s+या\s+नहीं\s+पता\s+नहीं",
        ]
    ]

    # -------------------------------------------------------------
    # 6. High Buying Intent (Positive Signal -> HIGH Strength)
    # -------------------------------------------------------------
    HIGH_INTENT_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\bi\s+want\s+to\s+buy\s+(?:it|this)\b",
            r"\bplease\s+place\s+my\s+order\b",
            r"\bplace\s+(?:an|my)\s+order\b",
            r"\bbook\s+my\s+(?:order|slot|seat)\b",
            r"\bhow\s+can\s+i\s+purchase\b",
            r"\bsend\s+(?:me\s+)?(?:the\s+)?payment\s+link\b",
            r"\bi\s+am\s+ready\s+to\s+proceed\b",
            r"\bi\s+want\s+to\s+(?:register|enroll|subscribe|sign\s+up)\b",
            r"\bcan\s+you\s+give\s+me\s+a\s+discount\b",
            r"\bgive\s+me\s+a\s+discount\b",
            r"\bany\s+discount\s+(?:available|possible)\b",
            r"\bproceed\s+with\s+(?:the\s+)?booking\b",
            r"\bwhere\s+do\s+i\s+pay\b",
            # Hindi / Hinglish
            r"\bmujhe\s+(?:yeh\s+)?khareedna\s+hai\b",
            r"\bmain\s+(?:ise\s+)?lena\s+(?:chahta|chahti)\s+hoon\b",
            r"\bmujhe\s+order\s+karna\s+hai\b",
            r"\bmera\s+order\s+book\s+(?:kardo|kar\s+dijiye|karo)\b",
            r"\bbooking\s+(?:kardo|kar\s*do|kar\s*dijiye|karo|kara\s*dya)\b",
            r"\bbook\s+(?:kardo|kar\s*do|kar\s*dijiye|karo)\b",
            r"\bbooking\s+kar\b",
            r"\bpayment\s+link\s+(?:bhej\s+do|bhejo|send\s+karo)\b",
            r"\bdiscount\s+(?:milega|dena|karo|do)\b",
            r"\baage\s+ki\s+prakriya\s+bataiye\b",
            r"\bmain\s+ready\s+hoon\b",
            r"\badmission\s+lena\s+hai\b",
            r"\bregistration\s+karna\s+hai\b",
            # Marathi
            r"\bmala\s+he\s+ghyayche\s+aahe\b",
            r"\bmala\s+he\s+kharedi\s+karayche\s+aahe\b",
            r"\bmajhi\s+order\s+book\s+kara\b",
            r"\bkahi\s+discount\s+milel\s+ka\b",
            r"\bpudhchi\s+prakriya\s+sanga\b",
            r"\bmala\s+he\s+utpadan\s+pahije\b",
            r"\bpayment\s+link\s+pathva\b",
            r"\bpudhe\s+kay\s+karayche\b",
            # Devanagari
            r"मला\s+हे\s+घ्यायचे\s+आहे",
            r"मला\s+हे\s+खरेदी\s+करायचे\s+आहे",
            r"माझी\s+ऑर्डर\s+बुक\s+करा",
            r"काही\s+सूट\s+मिळेल\s+का",
            r"पुढची\s+प्रक्रिया\s+सांगा",
            r"मला\s+हे\s+उत्पादन\s+पाहिजे",
            r"पेमेंट\s+लिंक\s+पाठवा",
            r"मला\s+यात\s+रस\s+आहे",
            r"मला\s+हे\s+हवे\s+आहे",
            r"मला\s+हे\s+पाहिजे",
            r"मुझे\s+यह\s+खरीदना\s+है",
            r"मैं\s+इसे\s+लेना\s+चाहता\s+हूँ",
            r"मैं\s+इसे\s+लेना\s+चाहती\s+हूँ",
            r"मुझे\s+ऑर्डर\s+करना\s+है",
            r"मेरा\s+ऑर्डर\s+बुक\s+कर\s+दीजिए",
            r"क्या\s+इसमें\s+कोई\s+छूट\s+मिलेगी",
            r"मुझे\s+यह\s+उत्पाद\s+चाहिए",
            r"आगे\s+की\s+प्रक्रिया\s+बताइए",
            r"पेमेंट\s+लिंक\s+भेजो",
            r"हाँ,\s*मुझे\s+इसमें\s+रुचि\s+है",
            r"रजिस्टर\s+(?:करना|होना)",
            r"एडमिशन\s+(?:लेना|चाहिए)",
        ]
    ]

    # -------------------------------------------------------------
    # 7. General Positive Interest (Positive Signal -> MEDIUM Strength)
    # -------------------------------------------------------------
    GENERAL_INTEREST_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(?:yes|yeah|yep|yup|haan|ha|ho|sure)\s*,?\s*(?:i\s+am|i'?m)?\s*interested\b",
            r"\bi\s+(?:am|m)\s+interested\b",
            r"\btell\s+me\s+more\b",
            r"\bi\s+want\s+to\s+know\s+more\b",
            r"\bthat\s+sounds\s+good\b",
            r"\bsounds\s+(?:great|interesting|good)\b",
            r"\bcan\s+you\s+(?:explain|tell|send|clarify|elaborate)\b",
            r"\b(?:yes\s*,?\s*)?please\s+explain\b",
            r"\bplease\s+(?:explain|elaborate|clarify)\b",
            r"\bsend\s+(?:me\s+)?(?:the\s+)?(?:details|info|information|brochure|catalogue|pdf|document)\b",
            r"\b(?:send|whatsapp|share)\s+(?:it\s+)?(?:on|to|via)\s+(?:whatsapp|mail|email|message|sms)\b",
            r"\b(?:details|jankari|mahiti)\s+(?:bhej|bhejo|send|share|pathva|dya|pahije)\b",
            r"\bi\s+would\s+like\s+to\s+try\s+it\b",
            r"\bi\s+want\s+to\s+try\s+it\b",
            r"\bcan\s+you\s+explain\s+the\s+benefits\b",
            r"\bexplain\s+the\s+benefits\b",
            r"\bwhatsapp\s+pe\s+(?:details|jankari|bhejo|send|share|dalo)\b",
            r"\bwhatsapp\s+var\s+(?:pathva|details|dya)\b",
            r"\bcan\s+i\s+get\s+a\s+demo\b",
            r"\bcan\s+someone\s+(?:contact|visit|call|meet)\s+me\b",
            r"\bwhat\s+happens\s+if\s+i\s+sign\s+up\b",
            # Hindi / Hinglish
            r"\bhaan\s*,?\s*(?:batao|bataiye|samjhao|explain\s+karo|boliye|sunao|sunte\s+hain)\b",
            r"\b(?:haan|ha|yes|ho|ji)?\s*,?\s*(?:mujhe\s+)?(?:isme\s+)?interest\s+hai\b",
            r"\b(?:mujhe\s+)?(?:iske|is\s+offer\s+ke|product\s+ke|service\s+ke)\s+baare\s+mein\s+(?:batao|bataiye|samjhao|explain\s+karo)\b",
            r"\b(?:iske\s+baare\s+mein\s+batao|iske\s+baare\s+mein\s+bataiye)\b",
            r"\bsun\s+raha\s+h(?:u|oon)\b",
            r"\bmujhe\s+iske\s+baare\s+mein\s+aur\s+jankari\s+chahiye\b",
            r"\biske\s+baare\s+mein\s+vistaar\s+se\s+bataiye\b",
            r"\bmujhe\s+poori\s+jankari\s+bhej\s+dijiye\b",
            r"\bmujhe\s+(?:chahiye|try\s+karna\s+hai|janana\s+hai|samajhna\s+hai|seekhna\s+hai)\b",
            r"\bdetails\s+bhejo\b",
            r"\bdemo\s+(?:dikhao|dikha|do|milega)\b",
            r"\baap\s+kya\s+provide\s+karte\s+hain\b",
            # Marathi
            r"\bho\s*,?\s*(?:sanga|sang\s+na|mahiti\s+dya|samjun\s+sanga)\b",
            r"\b(?:ho|yes)?\s*,?\s*(?:mala\s+)?(?:yat\s+)?interest\s+(?:aahe|ahe)\b",
            r"\b(?:mujhe|mala)\s+interest\s+(?:hai|aahe|ahe)\b",
            r"\bmala\s+yabaddal\s+adhik\s+mahiti\s+havi\s+aahe\b",
            r"\bmala\s+mahiti\s+pathva\b",
            r"\bmala\s+yabaddal\s+savistar\s+sanga\b",
            r"\bho\s+sir\s*,?\s*details\s+pathva\b",
            r"\byes\s+sir\s*,?\s*mala\s+information\s+pahije\b",
            r"\btry\s+karaycha\s+ahe\b",
            r"\bshikaycha\s+ahe\b",
            r"\bghyayla\s+aavdel\b",
            # Devanagari
            r"हाँ\s*,?\s*(?:बताओ|बताइए|समझाइए)",
            r"व्हाट्सएप\s+(?:पर|पे)\s+(?:भेज|भेजो|डालो)",
            r"माहिती\s+(?:पाठवा|द्या|पाहिजे)",
            r"हो\s*,?\s*(?:सांगा|माहिती\s+द्या)",
            r"डेमो\s+(?:दाखवा|मिळेल|दीजिए)",
            r"(?:मला\s+)?माहिती\s+.*(?:व्हॉट्सअॅप|व्हाट्सएप|व्हॉट्सॲप|व्हाट्सॲप|व्हाट्सअॅप|whatsapp).*(?:पाठवा|द्या)",
            r"(?:व्हॉट्सअॅप|व्हाट्सएप|व्हॉट्सॲप|व्हाट्सॲप|व्हाट्सअॅप|whatsapp).*(?:मला\s+)?माहिती\s+पाठवा",
            r"व्हॉट्सअॅपवर\s+पाठवा",
            r"व्हाट्सअॅपवर\s+पाठवा",
            r"(?:जानकारी|सूचना|डिटेल्स)\s+(?:चाहिए|दीजिए|दे\s+दो|बताइए|लेना\s+है|भेजो)",
            r"मुझे\s+इसके\s+बारे\s+में\s+और\s+जानकारी\s+चाहिए",
            r"इसके\s+बारे\s+में\s+विस्तार\s+से\s+बताइए",
            r"मुझे\s+पूरी\s+जानकारी\s+भेज\s+दीजिए",
            r"मला\s+याबद्दल\s+अधिक\s+माहिती\s+हवी\s+आहे",
            r"मला\s+माहिती\s+पाठवा",
            r"मला\s+याबद्दल\s+सविस्तर\s+सांगा",
            r"व्हाट्सएप\s+पर\s+(?:डिटेल्स|जानकारी)\s+भेजो",
            r"व्हाट्सअॅपवर\s+माहिती\s+पाठवा",
            r"व्हॉट्सअॅपवर\s+माहिती\s+पाठवा",
        ]
    ]

    # -------------------------------------------------------------
    # 8. Needs Information / Inquiries (NEEDS_INFORMATION Category)
    # -------------------------------------------------------------
    NEEDS_INFORMATION_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\bwhat\s+is\s+the\s+price\b",
            r"\bhow\s+much\s+(?:does\s+it\s+cost|is\s+it|do\s+you\s+charge|will\s+it\s+be)\b",
            r"\bhow\s+does\s+it\s+work\b",
            r"\bwhat\s+are\s+the\s+benefits\b",
            r"\bcan\s+you\s+explain\s+it\b",
            r"\bwhat\s+are\s+the\s+available\s+options\b",
            r"\bis\s+there\s+a\s+cheaper\s+option\b",
            r"\bwhat\s+is\s+included\s+in\s+the\s+package\b",
            r"\bhow\s+long\s+does\s+(?:it|the\s+setup|setup|installation|this|the\s+process)\s+take\b",
            r"\bwhat\s+plans?\s+do\s+you\s+have\b",
            r"\bwhat\s+are\s+the\s+charges\b",
            r"\bis\s+there\s+a\s+free\s+trial\b",
            r"\bfree\s+trial\b",
            r"\bwhat\s+are\s+the\s+specs\b",
            r"\bwhat\s+are\s+the\s+specifications\b",
            r"\bwhat\s+exactly\s+do\s+you\s+provide\b",
            r"\bhow\s+will\s+this\s+help\s+me\b",
            # Hindi / Hinglish
            r"\biski\s+keemat\s+kya\s+hai\b",
            r"\b(?:iska|inka|service\s+ka)?\s*(?:price|rate|cost|kharch|charges|paisa|fees?)\s*(?:kya|kitna)\s+hai\b",
            r"\bkitne\s+(?:ka|ki|ke|rupaiye|paise)\s+hai\b",
            r"\bkitna\s+(?:kharch|cost|paisa|charge|padega|lagega)\b",
            r"\bpehle\s+price\s+(?:batao|bataiye)\b",
            r"\bprice\s+(?:batao|bataiye)\b",
            r"\bkya\s+price\s+hai\b",
            r"\b(?:what\s+are|tell\s+me)\s+(?:your\s+)?prices?\b",
            r"\bwhat\s+(?:is|are)\s+the\s+(?:price|fees?|charges?|cost)\b",
            r"\bfees?\s+(?:kya|kitni)\s+hai\b",
            r"\bkeemat\s+kitni\s+hai\b",
            r"(?:याचे\s+)?दर\s+काय\s+आहेत",
            r"फीस\s+कितनी\s+है",
            r"कीमत\s+कितनी\s+है",
            r"\byeh\s+kaise\s+kaam\s+karta\s+hai\b",
            r"\bkaise\s+(?:work|kaam)\s+karta\s+hai\b",
            r"\biske\s+kya\s+(?:fayde|benefit)\s+hain\b",
            r"\bkya\s+(?:benefits?|fayde)\s+hain\s+(?:iske|is\s+service\s+ke)?\b",
            r"\b(?:iske\s+)?kya\s+(?:benefits?|fayde)\s+(?:hain|honge)\b",
            r"\bkya\s+benefit\s+hoga\b",
            r"\bkya\s+aap\s+samjha\s+sakte\s+hain\b",
            r"\biske\s+doosre\s+vikalp\s+kya\s+hain\b",
            r"\b(?:kya\s+)?koi\s+sasta\s+option\s+hai(?:\s+kya)?\b",
            r"\bkoi\s+sasta\s+(?:option|plan)\s+hai\b",
            r"\bpackage\s+(?:me|mein)\s+kya(?:\s*-\s*|\s+)kya\s+milega\b",
            r"\bpackage\s+(?:me|mein)\s+kya\s+milega\b",
            r"\bkya\s+kya\s+milega\b",
            r"\bwoh\s+plan\s+kitne\s+ka\s+hai\b",
            r"\bkya\s+plans?\s+hain\b",
            r"\bfree\s+trial\s+hai\s+kya\b",
            r"\bpehle\s+dekh\s+sakte\s+hain\s+kya\b",
            r"\bkaise\s+chalta\s+hai\b",
            r"\b(?:kahan|kidhar)\s+se\s+(?:seekhun|shuru\s+karun|milega)\b",
            r"\b(?:sawaal|sawal|doubt)\s+(?:hai|puchna|poochna)\b",
            # Marathi
            r"\byachi\s+kimat\s+kiti\s+aahe\b",
            r"\byachi\s+price\s+kiti\s+aahe\b",
            r"\bkiti\s+(?:rupaye|paise|charges|padel|kharch\s+hoil|kharch\s+yeil|lagel)\b",
            r"\bhe\s+kase\s+kaam\s+karte\b",
            r"\bkasa\s+chalto\b",
            r"\bkasa\s+work\s+karto\b",
            r"\bkay\s+(?:fayda|plans|offers?)\s+ahet?\b",
            r"\byache\s+fayde\s+kay\s+aahet\b",
            r"\btumhi\s+samjavun\s+sangu\s+shakta\s+ka\b",
            r"\bdusre\s+paryay\s+aahet\s+ka\b",
            r"\b(?:dusre\s+)?(?:kahi\s+)?options\s+ahe(?:t)?\s+ka\b",
            r"\byapeksha\s+swasta\s+paryay\s+aahe\s+ka\b",
            r"\b(?:kahi\s+)?swasta\s+(?:option|paryay)\s+aa?he\s+ka\b",
            r"\bto\s+plan\s+kiticha\s+ahe\b",
            r"\baadhi\s+try\s+karta\s+yeil\s+ka\b",
            # Devanagari
            r"इसकी\s+कीमत\s+क्या\s+है",
            r"किस्का\s+प्राइस\s+क्या\s+है",
            r"यह\s+कैसे\s+काम\s+करता\s+है",
            r"इसके\s+क्या\s+फायदे\s+हैं",
            r"क्या\s+आप\s+समझा\s+सकते\s+हैं",
            r"इसके\s+दूसरे\s+विकल्प\s+क्या\s+हैं",
            r"क्या\s+कोई\s+सस्ता\s+विकल्प\s+है",
            r"पैकेज\s+में\s+क्या[\s\-]?क्या\s+शामिल\s+है",
            r"(?:पैकेज|कोर्स|प्लान)\s+में\s+क्या\s+(?:शामिल\s+है|मिलेगा)",
            r"क्या[\s\-]?क्या\s+शामिल\s+है",
            r"याची\s+किंमत\s+किती\s+आहे",
            r"हे\s+कसे\s+काम\s+करते",
            r"याचे\s+फायदे\s+काय\s+आहेत",
            r"तुम्ही\s+समजावून\s+सांगू\s+शकता\s+का",
            r"दुसरे\s+पर्याय\s+आहेत\s+का",
            r"यापेक्षा\s+स्वस्त\s+पर्याय\s+आहे\s+का",
            r"कितने\s+का\s+है",
            r"कितना\s+(?:पड़ेगा|लगेगा)",
            r"किती\s+पडेल",
            r"खर्च\s+किती(?:\s+येईल)?",
            r"काय\s+फायदा\s+आहे",
            r"के\s+बारे\s+में\s+(?:बताओ|बताइए|जानना\s+है)",
        ]
    ]

    # -------------------------------------------------------------
    # 9. Callback Requested (CALLBACK_REQUESTED Category)
    # -------------------------------------------------------------
    CALLBACK_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(?:no\s*,?\s*)?call\s+me\s+tomorrow\b",
            r"\bplease\s+call\s+me\s+tomorrow\b",
            r"\bcall\s+me\s+(?:today\s+)?(?:at\s+)?\d+(?::\d+)?\s*(?:am|pm)?\b",
            r"\bcall\s+me\s+(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
            r"\bi\s*am\s*busy(?:\s*right\s*now|\s*now|\s*currently|\s*today)?\b",
            r"\bi'?m\s*busy(?:\s*right\s*now|\s*now|\s*currently|\s*today)?\b",
            r"\bneed\s*(?:some\s*)?time\s*to\s*(?:decide|think|discuss)\b",
            r"\bdiscuss\s*(?:it\s*)?with\s*(?:my\s*)?family\b",
            r"व्यस्त\s*(?:हूँ|हु|आहे)",
            r"उद्या\s*(?:फोन|कॉल)\s*(?:करा|बोलूया)",
            r"सोचने\s*(?:के\s*लिए|का)?\s*समय",
            r"विचार\s*करून\s*सांगतो",
            r"\bplease\s+call\s+me\s+later\b",
            r"\bcall\s+me\s+(?:later|in\s+the\s+evening|after\s+lunch|next\s+week|tonight|in\s+two\s+days)\b",
            r"\bcontact\s+me\s+(?:next\s+week|tomorrow|later)\b",
            r"\bi'?m\s+busy\s+now\s*[,;]?\s*(?:call|talk)\s+later\b",
            r"\bi\s+am\s+busy\s+(?:right\s+now|currently|today),\s*(?:call|talk)\s+later\b",
            r"\bcan\s+you\s+call\s+(?:next\s+week|later|tomorrow)\b",
            r"\bi'?m\s+(?:currently\s+)?driving\b",
            r"\bi\s+am\s+(?:currently\s+)?driving\b",
            r"\bi'?m\s+in\s+(?:a\s+)?meeting\b",
            r"\bi\s+am\s+in\s+a\s+meeting\b",
            r"\bin\s+(?:a\s+)?meeting\s+right\s+now\b",
            r"\bcan\s+you\s+ring\s+me\s+back\b",
            # Hindi / Hinglish
            r"\bmujhe\s+kal\s+(?:phone|call)\s+(?:kijiye|karna|karo)\b",
            r"\bkal\s+(?:call|phone)\s+(?:karna|karo|kijiye)\b",
            r"\bbaad\s+(?:me|mein)\s+(?:call|phone)\s*(?:kijiye|karna|karo|karenge|kara)?\b",
            r"\bbaad\s+(?:me|mein)\s+(?:call|phone|baat)\b",
            r"\bshaam\s+ko\s+.*(?:phone|call)\s+(?:karna|karo|kara|kijiye)\b",
            r"\bshaam\s+ko\s+(?:\d+\s+baje\s+)?(?:phone|call)\s+(?:karna|karo|kara|kijiye|kariye)\b",
            r"\babhi\s+busy\s+hoon\s*,?\s*(?:baad\s+(?:me|mein)|kal)\s+(?:phone|call)\s+(?:karna|karo)\b",
            r"\bagle\s+hafte\s+(?:phone|call|baat)\b",
            r"\bdriving\s+kar\s+raha\s+hoon\b",
            r"\bmeeting\s+(?:me|mein)\s+hoon\b",
            r"\bthodi\s+der\s+baad\s+call\s+karo\b",
            # Marathi
            r"\bmala\s+udya\s+(?:phone|call)\s+kara\b",
            r"\budya\s+(?:phone|call)\s+kara\b",
            r"\bnantar\s+(?:phone|call|bolu)\s+kara\b",
            r"\bsandhyakali\s+(?:phone|call)\s+kara\b",
            r"\baata\s+vel\s+nahi\s*,?\s*nantar\s+(?:phone|call)\s+kara\b",
            r"\bpudhchya\s+aathvadyat\s+(?:phone|call)\b",
            r"\bjevnanantar\s+(?:phone|call)\s+kara\b",
            r"\bgadi\s+chalavtoy\b",
            # Devanagari
            r"मला\s+उद्या\s+फोन\s+करा",
            r"नंतर\s+फोन\s+करा",
            r"संध्याकाळी\s+फोन\s+करा",
            r"आत्ता\s+वेळ\s+नाही\s*,?\s*नंतर\s+फोन\s+करा",
            r"पुढच्या\s+आठवड्यात\s+फोन\s+करा",
            r"जेवणानंतर\s+फोन\s+करा",
            r"मुझे\s+कल\s+फोन\s+कीजिए",
            r"बाद\s+में\s+कॉल\s+कीजिए",
            r"बाद\s+में\s+कॉल\s+करना",
            r"बाद\s+(?:में\s+)?बात\s+(?:करना|करेंगे|कीजिए|करते\s+हैं|करो)",
            r"बाद\s+बात\s+करना",
            r"शाम\s+को\s+फोन\s+करना",
            r"अभी\s+व्यस्त\s+हूँ\s*,?\s*बाद\s+में\s+फोन\s+करना",
            r"अगले\s+हफ्ते\s+फोन\s+कीजिए",
            r"मुझे\s+शाम\s+को\s+कॉल\s+करिए",
            r"उद्या\s+फोन\s+करा",
            r"नंतर\s+बोलू",
            r"(?:गाड़ी|कार)\s+(?:चला\s+रहा|ड्राइव\s+कर\s+रहा)",
            r"गाड़ी\s+चला\s+रहा\s+हूँ",
        ]
    ]

    # -------------------------------------------------------------
    # 10. Uncertain / Hesitation (UNCERTAIN Category)
    # -------------------------------------------------------------
    UNCERTAIN_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"^\s*maybe[\s\.,!]*$",
            r"\bi'?ll\s+think\s+about\s+it\b",
            r"\bi\s+(?:need\s+to|have\s+to|want\s+to)\s+think\s+about\s+it\b",
            r"\bi'?m\s+not\s+sure\b",
            r"\blet\s+me\s+decide\b",
            r"\bi'?ll\s+discuss\s+it\s+with\s+my\s+family\b",
            r"\bi'?ll\s+let\s+you\s+know\b",
            r"\bnot\s+right\s+now\b",
            r"\bi\s+need\s+some\s+time\b",
            r"\bi\s+haven'?t\s+decided\s+yet\b",
            r"\blet\s+me\s+think\b",
            r"\bif\s+the\s+price\s+is\s+(?:reasonable|low|cheap|good|okay)\b",
            # Hindi / Hinglish
            r"^\s*shayad[\s\.,!]*$",
            r"\bsochkar\s+(?:bataunga|bataungi)\b",
            r"\bsoch\s+kar\s+(?:batata|bataunga|bataungi|bolta)\b",
            r"\babhi\s+tay\s+nahi\s+kiya\s+hai\b",
            r"\bmujhe\s+thoda\s+samay\s+chahiye\b",
            r"\bthoda\s+time\s+chahiye\b",
            r"\bghar\s+(?:par|pe)\s+(?:puch|baat)\s+karke\b",
            r"\bghar\s+(?:par|pe)\s+poochkar\s+(?:bataunga|bataungi)\b",
            r"\babhi\s+nahi\s+pata\b",
            r"\bbaad\s+mein\s+batata\s+hoon\b",
            r"\bdekhte\s+hain\b",
            r"\babhi\s+sure\s+nahi\s+hoon\b",
            # Marathi
            r"^\s*baghuya[\s\.,!]*$",
            r"\bvichar\s+karun\s+(?:sangto|sangte)\b",
            r"\bajun\s+tharavle\s+nahi\b",
            r"\bmala\s+thoda\s+vel\s+dya\b",
            r"\bghari\s+vicharun\s+(?:sangto|sangte)\b",
            r"\bnantar\s+sangto\b",
            r"\bnantar\s+baghu\b",
            r"\bajun\s+nakki\s+nahi\b",
            # Devanagari
            r"^\s*शायद[\s\.,!]*$",
            r"सोचकर\s+बताऊँगा",
            r"सोचकर\s+बताऊँगी",
            r"सोच\s+के\s+बताता",
            r"अभी\s+तय\s+नहीं\s+किया\s+है",
            r"मुझे\s+थोड़ा\s+समय\s+चाहिए",
            r"घर\s+पर\s+पूछकर\s+बताऊँगा",
            r"घर\s+पर\s+पूछकर\s+बताऊँगी",
            r"अभी\s+नहीं\s+पता",
            r"बाद\s+में\s+बताता\s+हूँ",
            r"^\s*बघूया[\s\.,!]*$",
            r"विचार\s+करून\s+सांगतो",
            r"विचार\s+करून\s+सांगते",
            r"अजून\s+ठरवले\s+नाही",
            r"मला\s+थोडा\s+वेळ\s+द्या",
            r"घरी\s+विचारून\s+सांगतो",
            r"घरी\s+विचारून\s+सांगते",
            r"नंतर\s+सांगतो",
            r"नंतर\s+बघू",
        ]
    ]

    # -------------------------------------------------------------
    # 11. Skepticism / Objections
    # -------------------------------------------------------------
    SKEPTICISM_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\bi'?m\s+not\s+sure\s+this\s+will\s+work\b",
            r"\bi\s+don'?t\s+completely\s+trust\b",
            r"\bi'?m\s+currently\s+using\s+another\s+(?:company|provider|service)\b",
            r"\bwhy\s+should\s+i\s+switch\b",
            r"\blooks?\s+(?:a\s+bit\s+)?expensive\b",
            r"\btoo\s+expensive\b",
            r"\bcostly\s+lag\s+raha\s+hai\b",
            r"\bthoda\s+expensive\b",
            r"\bexpensive\s+lag\s+raha\s+hai\b",
            r"\bmehnga\s+(?:lag\s+raha|hai)\b",
            r"\bmahag\s+vatatay\b",
            r"\bmahag\s+aahe\b",
            r"\btrust\s+nahi\s+ho\s+raha\b",
            r"महंगा\s+लग\s+रहा\s+है",
            r"महाग\s+आहे",
            r"विश्वास\s+नाही\s+बसत",
        ]
    ]

    # Mixed Objection BUT Interested
    OBJECTION_BUT_INTERESTED_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(?:expensive|costly|pricey)\s*,?\s*but\s+(?:i'?m|i\s+am)?\s*interested\b",
            r"\b(?:expensive|costly|pricey)\s*,?\s*but\s+(?:what|how|can|is)\b",
            r"\bmehnga\s+hai\s*,?\s*(?:lekin|par)\s*(?:mujhe\s+)?(?:interest\s+hai|chahiye|lena\s+hai|kya|kaise)\b",
            r"\bmahag\s+aahe\s*,?\s*pan\s*(?:ghyayche\s+aahe|aavdel|pahije|kay|kasa)\b",
            r"महाग\s+आहे\s*,?\s*पण\s*घ्यायचे\s+आहे",
            r"महंगा\s+है\s*,?\s*लेकिन\s*मुझे\s*(?:रुचि\s+है|लेना\s+है)",
        ]
    ]

    # Mixed Objection AND Rejected
    OBJECTION_AND_REJECTED_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"\b(?:expensive|costly|pricey)\s*[\.,!]?\s*(?:i\s+don'?t\s+want\s+it|not\s+interested|no\s+thanks|i\s+don'?t\s+need)\b",
            r"\bmehnga\s+hai\s*[\.,!]?\s*(?:nahi\s+chahiye|nahi\s+lena|nako)\b",
            r"\bmahag\s+aahe\s*[\.,!]?\s*(?:nako|nahi\s+pahije)\b",
            r"महाग\s+आहे\s*[\.,!]?\s*नको",
            r"महंगा\s+है\s*[\.,!]?\s*नहीं\s+चाहिए",
        ]
    ]

    # -------------------------------------------------------------
    # 12. Pure Acoustic Disconnects / Silent Calls
    # -------------------------------------------------------------
    EMPTY_OR_GREETING_PATTERNS: List[Pattern] = [
        re.compile(p, re.IGNORECASE) for p in [
            r"^(?:hello|hi|hey|haan|ha|ji|bolo|boliye|aawaz\s+nahi\s+aa\s+rahi|hello\s*\?)+$",
            r"^\[?call\s+(?:disconnected|ended|dropped)\]?$",
            r"^(?:hello\s*\?\s*)+$",
            r"^(?:kaun\s*\?\s*)+$",
        ]
    ]

    @classmethod
    def match_any(cls, text: str, patterns: List[Pattern]) -> bool:
        """Checks if text matches any regex in the pattern list."""
        if not text:
            return False
        cleaned = TextNormalizer.normalize(text)
        for pattern in patterns:
            if pattern.search(cleaned) or pattern.search(text):
                return True
        return False

    @classmethod
    def extract_signals_from_text(cls, text: str) -> List[str]:
        """Identifies all positive, negative, callback, inquiry, skepticism, and uncertainty signals."""
        signals = []
        cleaned = TextNormalizer.normalize(text)

        # 1. Negative & Opt-out signals
        if cls.match_any(text, cls.OPT_OUT_PATTERNS) or cls.match_any(cleaned, cls.OPT_OUT_PATTERNS):
            signals.append("OPT_OUT")
        if cls.match_any(text, cls.WRONG_PERSON_PATTERNS) or cls.match_any(cleaned, cls.WRONG_PERSON_PATTERNS):
            signals.append("WRONG_PERSON")
        if cls.match_any(text, cls.EXPLICIT_REJECTION_PATTERNS) or cls.match_any(cleaned, cls.EXPLICIT_REJECTION_PATTERNS):
            signals.append("REJECTION")
        if cls.match_any(text, cls.INDIRECT_REJECTION_PATTERNS) or cls.match_any(cleaned, cls.INDIRECT_REJECTION_PATTERNS):
            signals.append("INDIRECT_REJECTION")

        # 2. Negation Scoping
        if cls.match_any(text, cls.UNCERTAIN_NEGATION_PATTERNS) or cls.match_any(cleaned, cls.UNCERTAIN_NEGATION_PATTERNS):
            signals.append("UNCERTAIN_NEGATION")

        # 3. Mixed Sentiment & Objections
        if cls.match_any(text, cls.OBJECTION_BUT_INTERESTED_PATTERNS) or cls.match_any(cleaned, cls.OBJECTION_BUT_INTERESTED_PATTERNS):
            signals.append("OBJECTION_BUT_INTERESTED")
        if cls.match_any(text, cls.OBJECTION_AND_REJECTED_PATTERNS) or cls.match_any(cleaned, cls.OBJECTION_AND_REJECTED_PATTERNS):
            signals.append("OBJECTION_AND_REJECTED")
        if cls.match_any(text, cls.SKEPTICISM_PATTERNS) or cls.match_any(cleaned, cls.SKEPTICISM_PATTERNS):
            signals.append("SKEPTICISM")

        # 4. Positive Signals
        if cls.match_any(text, cls.HIGH_INTENT_PATTERNS) or cls.match_any(cleaned, cls.HIGH_INTENT_PATTERNS):
            signals.append("HIGH_INTENT")
        if cls.match_any(text, cls.GENERAL_INTEREST_PATTERNS) or cls.match_any(cleaned, cls.GENERAL_INTEREST_PATTERNS):
            signals.append("GENERAL_INTEREST")

        # 5. Information Seeking
        if cls.match_any(text, cls.NEEDS_INFORMATION_PATTERNS) or cls.match_any(cleaned, cls.NEEDS_INFORMATION_PATTERNS):
            signals.append("NEEDS_INFORMATION")

        # 6. Callback
        if cls.match_any(text, cls.CALLBACK_PATTERNS) or cls.match_any(cleaned, cls.CALLBACK_PATTERNS):
            signals.append("CALLBACK_REQUESTED")

        # 7. Uncertain
        if cls.match_any(text, cls.UNCERTAIN_PATTERNS) or cls.match_any(cleaned, cls.UNCERTAIN_PATTERNS):
            signals.append("UNCERTAIN")

        return signals

    @classmethod
    def detect_languages(cls, text: str) -> List[str]:
        """Detects whether transcript contains English, Hindi, Marathi, Hinglish, or Marathish."""
        languages: Set[str] = set()
        if not text:
            return ["English"]

        # Devanagari detection
        if re.search(r"[\u0900-\u097F]", text):
            marathi_dev_keywords = ["आहे", "नाही", "नको", "करा", "पाठवा", "सांगा", "होय", "पाहिजे", "करायचे", "घ्यायचे", "बघूया"]
            if any(k in text for k in marathi_dev_keywords):
                languages.add("Marathi")
            else:
                languages.add("Hindi")

        # Romanized keywords
        hindi_keywords = {
            "kya", "kaise", "hai", "nahi", "chahiye", "batao", "bhejo", "soch", 
            "zarurat", "hum", "aap", "aur", "pehle", "batana", "tha", "achha", "iska",
            "khareedna", "lena", "karna", "baad", "kal", "shaam", "poochkar", "dekhte"
        }
        marathi_keywords = {
            "ahe", "aahe", "nako", "nakoy", "nakos", "sang", "sanga", "kasa", "kiti", 
            "pathva", "mahiti", "padel", "vichar", "nantar", "mahag", "majha", "udya",
            "ghyayche", "kharedi", "pahije", "baghuya", "tharavle", "ghari"
        }
        english_keywords = {
            "interested", "service", "explain", "price", "cost", "details", 
            "whatsapp", "tomorrow", "register", "company", "call", "product",
            "discount", "purchase", "order", "package", "benefits", "maybe",
            "specs", "specifications"
        }

        text_lower = text.lower()
        words = set(re.findall(r"\b[a-z]+\b", text_lower))

        has_hindi = bool(words & hindi_keywords)
        has_marathi = bool(words & marathi_keywords)
        has_english = bool(words & english_keywords)

        if has_hindi and has_english:
            languages.add("Hinglish")
        elif has_hindi:
            languages.add("Hindi/Hinglish")

        if has_marathi and has_english:
            languages.add("Marathish")
        elif has_marathi:
            languages.add("Marathi")

        if has_english and not (has_hindi or has_marathi):
            languages.add("English")

        if not languages:
            languages.add("English")

        return sorted(list(languages))
