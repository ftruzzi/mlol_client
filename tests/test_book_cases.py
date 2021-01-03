def case_book():
    return "150208516", {
        "id": "150208516",
        "title": "Spillover. L'evoluzione delle pandemie",
        "authors": ["David Quammen"],
        "publisher": "Adelphi",
        "ISBNs": ["9788845982484", "9788845932045"],
        "language": "italiano",
        "categories": [
            ["Scienze umane", "Storia", "Storia culturale e sociale"],
            [
                "Medicina",
                "Altre branche della medicina",
                "Microbiologia e virologia medica",
            ],
            [
                "Matematica e scienze",
                "Scienze: argomenti d'interesse generale",
                "Biologia, scienze della vita",
                "Scienze: opere divulgative",
            ],
        ],
        "year": 2020,
        "formats": ["epub"],
        "drm": True,
    }


def case_book_multiple_authors():
    return "150232512", {"authors": ["Mauro Ceré", "Dario Spelta"]}


def case_book_multiple_formats_drm():
    return "150226541", {"formats": ["pdf", "epub"], "drm": True}


def case_book_multiple_formats_nodrm():
    return "850636151", {"formats": ["epub", "mobi"], "drm": False}
