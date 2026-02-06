from schoolbot.downloader import simplify_course_name
tests = [
    'ENGLISH 8: Green 8 ENGLISH 8',
    'EXPLORING MUSIC 8: 0528 270 EXPLORING MUSIC 8',
    'GR 8 MATH 8 - 2 412: 0458 3 GR 8 MATH 8 - 2 412',
    'GR 8 SPANISH 313: Cooper 8',
    'KEYSTONE: 99023 43 KEYSTONE',
    'PHYS.ED.8: 0608 2711 PHYS.ED.8',
    'SCIENCE 8: Cooper 8 Science YELLOW',
    'SOCIAL STUDIES 8: 0758 5 SOCIAL STUDIES 8',
    'TECHNOLOGY 8: Q3 Period 8 Cooper',
]
for t in tests:
    print(f'{t:55s} -> {simplify_course_name(t)}')
