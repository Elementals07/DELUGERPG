"""
Canonical Evolution Graph and Rarity Classifier for DelugeRPG.
Maps 1,107 Pokémon species into canonical evolution family trees, evolution stages (1=base, 2=middle, 3=final),
and rarity tiers (starter, legendary, mythical, ultra_beast, paradox, regular).
"""

from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass
import sqlite3


@dataclass
class EvolutionInfo:
    species_name: str
    base_species: str
    evolution_stage: int  # 1: base, 2: stage 1, 3: stage 2
    evolves_from: Optional[str]
    evolves_to: List[str]
    category: str  # 'starter', 'legendary', 'mythical', 'ultra_beast', 'paradox', 'regular'


# Comprehensive canonical classification lists
STARTER_FAMILIES = {
    # Gen 1-9 Starter base species
    "Bulbasaur", "Charmander", "Squirtle",
    "Chikorita", "Cyndaquil", "Totodile",
    "Treecko", "Torchic", "Mudkip",
    "Turtwig", "Chimchar", "Piplup",
    "Snivy", "Tepig", "Oshawott",
    "Chespin", "Fennekin", "Froakie",
    "Rowlet", "Litten", "Popplio",
    "Grookey", "Scorbunny", "Sobble",
    "Sprigatito", "Fuecoco", "Quaxly"
}

LEGENDARIES = {
    "Articuno", "Zapdos", "Moltres", "Mewtwo",
    "Raikou", "Entei", "Suicune", "Lugia", "Ho-Oh",
    "Regirock", "Regice", "Registeel", "Latias", "Latios", "Kyogre", "Groudon", "Rayquaza",
    "Uxie", "Mesprit", "Azelf", "Dialga", "Palkia", "Heatran", "Regigigas", "Giratina", "Cresselia",
    "Cobalion", "Terrakion", "Virizion", "Tornadus", "Thundurus", "Reshiram", "Zekrom", "Landorus", "Kyurem",
    "Xerneas", "Yveltal", "Zygarde",
    "Type: Null", "Silvally", "Tapu Koko", "Tapu Lele", "Tapu Bulu", "Tapu Fini",
    "Cosmog", "Cosmoem", "Solgaleo", "Lunala", "Necrozma",
    "Zacian", "Zamazenta", "Eternatus", "Kubfu", "Urshifu", "Regieleki", "Regidrago", "Glastrier", "Spectrier", "Calyrex",
    "Wo-Chien", "Chien-Pao", "Ting-Lu", "Chi-Yu", "Koraidon", "Miraidon",
    "Okidogi", "Munkidori", "Fezandipiti", "Ogerpon", "Terapagos"
}

MYTHICALS = {
    "Mew", "Celebi", "Jirachi", "Deoxys", "Phione", "Manaphy", "Darkrai", "Shaymin", "Arceus",
    "Victini", "Keldeo", "Meloetta", "Genesect", "Diancie", "Hoopa", "Volcanion",
    "Magearna", "Marshadow", "Zeraora", "Meltan", "Melmetal", "Zarude", "Pecharunt"
}

ULTRA_BEASTS = {
    "Nihilego", "Buzzwole", "Pheromosa", "Xurkitree", "Celesteela", "Kartana", "Guzzlord",
    "Poipole", "Naganadel", "Stakataka", "Blacephalon"
}

PARADOX_POKEMON = {
    "Great Tusk", "Scream Tail", "Brute Bonnet", "Flutter Mane", "Slither Wing", "Sandy Shocks", "Roaring Moon",
    "Iron Treads", "Iron Bundle", "Iron Hands", "Iron Jugulis", "Iron Moth", "Iron Thorns", "Iron Valiant",
    "Walking Wake", "Iron Leaves", "Gouging Fire", "Raging Bolt", "Iron Boulder", "Iron Crown"
}

# Canonical evolution lines (base -> [stage 2, stage 3])
# Chains format: (Stage 1, Stage 2, Stage 3) or (Stage 1, Stage 2) or branching dictionaries
EVOLUTION_CHAINS = [
    # Gen 1 Starters & Regulars
    ("Bulbasaur", "Ivysaur", "Venusaur"),
    ("Charmander", "Charmeleon", "Charizard"),
    ("Squirtle", "Wartortle", "Blastoise"),
    ("Caterpie", "Metapod", "Butterfree"),
    ("Weedle", "Kakuna", "Beedrill"),
    ("Pidgey", "Pidgeotto", "Pidgeot"),
    ("Rattata", "Raticate"),
    ("Spearow", "Fearow"),
    ("Ekans", "Arbok"),
    ("Pichu", "Pikachu", "Raichu"),
    ("Sandshrew", "Sandslash"),
    ("Nidoran♀", "Nidorina", "Nidoqueen"),
    ("Nidoran♂", "Nidorino", "Nidoking"),
    ("Cleffa", "Clefairy", "Clefable"),
    ("Vulpix", "Ninetales"),
    ("Igglybuff", "Jigglypuff", "Wigglytuff"),
    ("Zubat", "Golbat", "Crobat"),
    ("Oddish", "Gloom", "Vileplume"),
    ("Paras", "Parasect"),
    ("Venonat", "Venomoth"),
    ("Diglett", "Dugtrio"),
    ("Meowth", "Persian"),
    ("Psyduck", "Golduck"),
    ("Mankey", "Primeape", "Annihilape"),
    ("Growlithe", "Arcanine"),
    ("Poliwag", "Poliwhirl", "Poliwrath"),
    ("Abra", "Kadabra", "Alakazam"),
    ("Machop", "Machoke", "Machamp"),
    ("Bellsprout", "Weepinbell", "Victreebel"),
    ("Tentacool", "Tentacruel"),
    ("Geodude", "Graveler", "Golem"),
    ("Ponyta", "Rapidash"),
    ("Slowpoke", "Slowbro"),
    ("Magnemite", "Magneton", "Magnezone"),
    ("Doduo", "Dodrio"),
    ("Seel", "Dewgong"),
    ("Grimer", "Muk"),
    ("Shellder", "Cloyster"),
    ("Gastly", "Haunter", "Gengar"),
    ("Onix", "Steelix"),
    ("Drowzee", "Hypno"),
    ("Krabby", "Kingler"),
    ("Voltorb", "Electrode"),
    ("Exeggcute", "Exeggutor"),
    ("Cubone", "Marowak"),
    ("Tyrogue", "Hitmonlee"),
    ("Lickitung", "Lickilicky"),
    ("Koffing", "Weezing"),
    ("Rhyhorn", "Rhydon", "Rhyperior"),
    ("Happiny", "Chansey", "Blissey"),
    ("Tangela", "Tangrowth"),
    ("Kangaskhan",),
    ("Horsea", "Seadra", "Kingdra"),
    ("Goldeen", "Seaking"),
    ("Staryu", "Starmie"),
    ("Mime Jr.", "Mr. Mime"),
    ("Scyther", "Scizor", "Kleavor"),
    ("Smoochum", "Jynx"),
    ("Elekid", "Electabuzz", "Electivire"),
    ("Magby", "Magmar", "Magmortar"),
    ("Pinsir",),
    ("Tauros",),
    ("Magikarp", "Gyarados"),
    ("Lapras",),
    ("Ditto",),
    ("Eevee",),
    ("Porygon", "Porygon2", "Porygon-Z"),
    ("Omanyte", "Omastar"),
    ("Kabuto", "Kabutops"),
    ("Aerodactyl",),
    ("Munchlax", "Snorlax"),
    ("Dratini", "Dragonair", "Dragonite"),

    # Gen 2
    ("Chikorita", "Bayleef", "Meganium"),
    ("Cyndaquil", "Quilava", "Typhlosion"),
    ("Totodile", "Croconaw", "Feraligatr"),
    ("Sentret", "Furret"),
    ("Hoothoot", "Noctowl"),
    ("Ledyba", "Ledian"),
    ("Spinarak", "Ariados"),
    ("Chinchou", "Lanturn"),
    ("Togepi", "Togetic", "Togekiss"),
    ("Natu", "Xatu"),
    ("Mareep", "Flaaffy", "Ampharos"),
    ("Bonsly", "Sudowoodo"),
    ("Hoppip", "Skiploom", "Jumpluff"),
    ("Aipom", "Ambipom"),
    ("Sunkern", "Sunflora"),
    ("Yanma", "Yanmega"),
    ("Wooper", "Quagsire"),
    ("Murkrow", "Honchkrow"),
    ("Misdreavus", "Mismagius"),
    ("Unown",),
    ("Wynaut", "Wobbuffet"),
    ("Girafarig", "Farigiraf"),
    ("Pineco", "Forretress"),
    ("Dunsparce", "Dudunsparce"),
    ("Gligar", "Gliscor"),
    ("Snubbull", "Granbull"),
    ("Qwilfish", "Overqwil"),
    ("Shuckle",),
    ("Heracross",),
    ("Sneasel", "Weavile"),
    ("Teddiursa", "Ursaring", "Ursaluna"),
    ("Slugma", "Magcargo"),
    ("Swinub", "Piloswine", "Mamoswine"),
    ("Corsola", "Cursola"),
    ("Remoraid", "Octillery"),
    ("Delibird",),
    ("Mantine",),
    ("Skarmory",),
    ("Houndour", "Houndoom"),
    ("Phanpy", "Donphan"),
    ("Stantler", "Wyrdeer"),
    ("Smeargle",),
    ("Miltank",),
    ("Larvitar", "Pupitar", "Tyranitar"),

    # Gen 3
    ("Treecko", "Grovyle", "Sceptile"),
    ("Torchic", "Combusken", "Blaziken"),
    ("Mudkip", "Marshtomp", "Swampert"),
    ("Poochyena", "Mightyena"),
    ("Zigzagoon", "Linoone", "Obstagoon"),
    ("Wurmple", "Silcoon", "Beautifly"),
    ("Lotad", "Lombre", "Ludicolo"),
    ("Seedot", "Nuzleaf", "Shiftry"),
    ("Taillow", "Swellow"),
    ("Wingull", "Pelipper"),
    ("Ralts", "Kirlia", "Gardevoir"),
    ("Surskit", "Masquerain"),
    ("Shroomish", "Breloom"),
    ("Slakoth", "Vigoroth", "Slaking"),
    ("Nincada", "Ninjask"),
    ("Whismur", "Loudred", "Exploud"),
    ("Makuhita", "Hariyama"),
    ("Azurill", "Marill", "Azumarill"),
    ("Nosepass", "Probopass"),
    ("Skitty", "Delcatty"),
    ("Sableye",),
    ("Mawile",),
    ("Aron", "Lairon", "Aggron"),
    ("Meditite", "Medicham"),
    ("Electrike", "Manectric"),
    ("Plusle",),
    ("Minun",),
    ("Volbeat",),
    ("Illumise",),
    ("Budew", "Roselia", "Roserade"),
    ("Gulpin", "Swalot"),
    ("Carvanha", "Sharpedo"),
    ("Wailmer", "Wailord"),
    ("Numel", "Camerupt"),
    ("Torkoal",),
    ("Spoink", "Grumpig"),
    ("Spinda",),
    ("Trapinch", "Vibrava", "Flygon"),
    ("Cacnea", "Cacturne"),
    ("Swablu", "Altaria"),
    ("Zangoose",),
    ("Seviper",),
    ("Lunatone",),
    ("Solrock",),
    ("Barboach", "Whiscash"),
    ("Corphish", "Crawdaunt"),
    ("Baltoy", "Claydol"),
    ("Lileep", "Cradily"),
    ("Anorith", "Armaldo"),
    ("Feebas", "Milotic"),
    ("Castform",),
    ("Kecleon",),
    ("Shuppet", "Banette"),
    ("Duskull", "Dusclops", "Dusknoir"),
    ("Tropius",),
    ("Chingling", "Chimecho"),
    ("Absol",),
    ("Snorunt", "Glalie"),
    ("Spheal", "Sealeo", "Walrein"),
    ("Clamperl", "Huntail"),
    ("Relicanth",),
    ("Luvdisc",),
    ("Bagon", "Shelgon", "Salamence"),
    ("Beldum", "Metang", "Metagross"),

    # Gen 4
    ("Turtwig", "Grotle", "Torterra"),
    ("Chimchar", "Monferno", "Infernape"),
    ("Piplup", "Prinplup", "Empoleon"),
    ("Starly", "Staravia", "Staraptor"),
    ("Bidoof", "Bibarel"),
    ("Kricketot", "Kricketune"),
    ("Shinx", "Luxio", "Luxray"),
    ("Cranidos", "Rampardos"),
    ("Shieldon", "Bastiodon"),
    ("Burmy", "Wormadam"),
    ("Combee", "Vespiquen"),
    ("Pachirisu",),
    ("Buizel", "Floatzel"),
    ("Cherubi", "Cherrim"),
    ("Shellos", "Gastrodon"),
    ("Drifloon", "Drifblim"),
    ("Buneary", "Lopunny"),
    ("Glameow", "Purugly"),
    ("Stunky", "Skuntank"),
    ("Bronzor", "Bronzong"),
    ("Chatot",),
    ("Spiritomb",),
    ("Gible", "Gabite", "Garchomp"),
    ("Riolu", "Lucario"),
    ("Hippopotas", "Hippowdon"),
    ("Skorupi", "Drapion"),
    ("Croagunk", "Toxicroak"),
    ("Carnivine",),
    ("Finneon", "Lumineon"),
    ("Snover", "Abomasnow"),
    ("Rotom",),

    # Gen 5
    ("Snivy", "Servine", "Serperior"),
    ("Tepig", "Pignite", "Emboar"),
    ("Oshawott", "Dewott", "Samurott"),
    ("Patrat", "Watchog"),
    ("Lillipup", "Herdier", "Stoutland"),
    ("Purrloin", "Liepard"),
    ("Pansage", "Simisage"),
    ("Pansear", "Simisear"),
    ("Panpour", "Simipour"),
    ("Munna", "Musharna"),
    ("Pidove", "Tranquill", "Unfezant"),
    ("Blitzle", "Zebstrika"),
    ("Roggenrola", "Boldore", "Gigalith"),
    ("Woobat", "Swoobat"),
    ("Drilbur", "Excadrill"),
    ("Audino",),
    ("Timburr", "Gurdurr", "Conkeldurr"),
    ("Tympole", "Palpitoad", "Seismitoad"),
    ("Throh",),
    ("Sawk",),
    ("Sewaddle", "Swadloon", "Leavanny"),
    ("Venipede", "Whirlipede", "Scolipede"),
    ("Cottonee", "Whimsicott"),
    ("Petilil", "Lilligant"),
    ("Basculin", "Basculegion"),
    ("Sandile", "Krokorok", "Krookodile"),
    ("Darumaka", "Darmanitan"),
    ("Maractus",),
    ("Dwebble", "Crustle"),
    ("Scraggy", "Scrafty"),
    ("Sigilyph",),
    ("Yamask", "Cofagrigus"),
    ("Tirtouga", "Carracosta"),
    ("Archen", "Archeops"),
    ("Trubbish", "Garbodor"),
    ("Zorua", "Zoroark"),
    ("Minccino", "Cinccino"),
    ("Gothita", "Gothorita", "Gothitelle"),
    ("Solosis", "Duosion", "Reuniclus"),
    ("Ducklett", "Swanna"),
    ("Vanillite", "Vanillish", "Vanilluxe"),
    ("Deerling", "Sawsbuck"),
    ("Emolga",),
    ("Karrablast", "Escavalier"),
    ("Foongus", "Amoonguss"),
    ("Frillish", "Jellicent"),
    ("Alomomola",),
    ("Joltik", "Galvantula"),
    ("Ferroseed", "Ferrothorn"),
    ("Klink", "Klang", "Klinklang"),
    ("Tynamo", "Eelektrik", "Eelektross"),
    ("Elgyem", "Beheeyem"),
    ("Litwick", "Lampent", "Chandelure"),
    ("Axew", "Fraxure", "Haxorus"),
    ("Cubchoo", "Beartic"),
    ("Cryogonal",),
    ("Shelmet", "Accelgor"),
    ("Stunfisk",),
    ("Mienfoo", "Mienshao"),
    ("Druddigon",),
    ("Golett", "Golurk"),
    ("Pawniard", "Bisharp", "Kingambit"),
    ("Bouffalant",),
    ("Rufflet", "Braviary"),
    ("Vullaby", "Mandibuzz"),
    ("Heatmor",),
    ("Durant",),
    ("Deino", "Zweilous", "Hydreigon"),
    ("Larvesta", "Volcarona"),

    # Gen 6
    ("Chespin", "Quilladin", "Chesnaught"),
    ("Fennekin", "Braixen", "Delphox"),
    ("Froakie", "Frogadier", "Greninja"),
    ("Bunnelby", "Diggersby"),
    ("Fletchling", "Fletchinder", "Talonflame"),
    ("Scatterbug", "Spewpa", "Vivillon"),
    ("Litleo", "Pyroar"),
    ("Flabébé", "Floette", "Florges"),
    ("Skiddo", "Gogoat"),
    ("Pancham", "Pangoro"),
    ("Furfrou",),
    ("Espurr", "Meowstic"),
    ("Honedge", "Doublade", "Aegislash"),
    ("Spritzee", "Aromatisse"),
    ("Swirlix", "Slurpuff"),
    ("Inkay", "Malamar"),
    ("Binacle", "Barbaracle"),
    ("Skrelp", "Dragalge"),
    ("Clauncher", "Clawitzer"),
    ("Helioptile", "Heliolisk"),
    ("Tyrunt", "Tyrantrum"),
    ("Amaura", "Aurorus"),
    ("Hawlucha",),
    ("Dedenne",),
    ("Carbink",),
    ("Goomy", "Sliggoo", "Goodra"),
    ("Klefki",),
    ("Phantump", "Trevenant"),
    ("Pumpkaboo", "Gourgeist"),
    ("Bergmite", "Avalugg"),
    ("Noibat", "Noivern"),

    # Gen 7
    ("Rowlet", "Dartrix", "Decidueye"),
    ("Litten", "Torracat", "Incineroar"),
    ("Popplio", "Brionne", "Primarina"),
    ("Pikipek", "Trumbeak", "Toucannon"),
    ("Yungoos", "Gumshoos"),
    ("Grubbin", "Charjabug", "Vikavolt"),
    ("Crabrawler", "Crabominable"),
    ("Oricorio",),
    ("Cutiefly", "Ribombee"),
    ("Rockruff", "Lycanroc"),
    ("Wishiwashi",),
    ("Mareanie", "Toxapex"),
    ("Mudbray", "Mudsdale"),
    ("Dewpider", "Araquanid"),
    ("Fomantis", "Lurantis"),
    ("Morelull", "Shiinotic"),
    ("Salandit", "Salazzle"),
    ("Stufful", "Bewear"),
    ("Bounsweet", "Steenee", "Tsareena"),
    ("Comfey",),
    ("Oranguru",),
    ("Passimian",),
    ("Wimpod", "Golisopod"),
    ("Sandygast", "Palossand"),
    ("Pyukumuku",),
    ("Minior",),
    ("Komala",),
    ("Turtonator",),
    ("Togedemaru",),
    ("Mimikyu",),
    ("Bruxish",),
    ("Drampa",),
    ("Dhelmise",),
    ("Jangmo-o", "Hakamo-o", "Kommo-o"),

    # Gen 8
    ("Grookey", "Thwackey", "Rillaboom"),
    ("Scorbunny", "Raboot", "Cinderace"),
    ("Sobble", "Drizzile", "Inteleon"),
    ("Skwovet", "Greedent"),
    ("Rookidee", "Corvisquire", "Corviknight"),
    ("Blipbug", "Dottler", "Orbeetle"),
    ("Nickit", "Thievul"),
    ("Gossifleur", "Eldegoss"),
    ("Wooloo", "Dubwool"),
    ("Chewtle", "Drednaw"),
    ("Yamper", "Boltund"),
    ("Rolycoly", "Carkol", "Coalossal"),
    ("Applin", "Flapple"),
    ("Silicobra", "Sandaconda"),
    ("Cramorant",),
    ("Arrokuda", "Barraskewda"),
    ("Toxel", "Toxtricity"),
    ("Sizzlipede", "Centiskorch"),
    ("Clobbopus", "Grapploct"),
    ("Sinistea", "Polteageist"),
    ("Hatenna", "Hattrem", "Hatterene"),
    ("Impidimp", "Morgrem", "Grimmsnarl"),
    ("Milcery", "Alcremie"),
    ("Falinks",),
    ("Pincurchin",),
    ("Snom", "Frosmoth"),
    ("Stonjourner",),
    ("Eiscue",),
    ("Indeedee",),
    ("Morpeko",),
    ("Cufant", "Copperajah"),
    ("Dracozolt",),
    ("Arctozolt",),
    ("Dracovish",),
    ("Arctovish",),
    ("Duraludon", "Archaludon"),
    ("Dreepy", "Drakloak", "Dragapult"),

    # Gen 9
    ("Sprigatito", "Floragato", "Meowscarada"),
    ("Fuecoco", "Crocalor", "Skeledirge"),
    ("Quaxly", "Quaxwell", "Quaquaval"),
    ("Lechonk", "Oinkologne"),
    ("Tarountula", "Spidops"),
    ("Nymble", "Lokix"),
    ("Pawmi", "Pawmo", "Pawmot"),
    ("Tandemaus", "Maushold"),
    ("Fidough", "Dachsbun"),
    ("Smoliv", "Dolliv", "Arboliva"),
    ("Squawkabilly",),
    ("Nacli", "Naclstack", "Garganacl"),
    ("Charcadet", "Armarouge"),
    ("Tadbulb", "Bellibolt"),
    ("Wattrel", "Kilowattrel"),
    ("Maschiff", "Mabosstiff"),
    ("Shroodle", "Grafaiai"),
    ("Bramblin", "Brambleghast"),
    ("Toedscool", "Toedscruel"),
    ("Klawf",),
    ("Capsakid", "Scovillain"),
    ("Rellor", "Rabsca"),
    ("Flittle", "Espathra"),
    ("Tinkatink", "Tinkatuff", "Tinkaton"),
    ("Wiglett", "Wugtrio"),
    ("Bombirdier",),
    ("Finizen", "Palafin"),
    ("Varoom", "Revavroom"),
    ("Cyclizar",),
    ("Orthworm",),
    ("Glimmet", "Glimmora"),
    ("Greavard", "Houndstone"),
    ("Flamigo",),
    ("Cetoddle", "Cetitan"),
    ("Veluza",),
    ("Dondozo",),
    ("Tatsugiri",),
    ("Frigibax", "Arctibax", "Baxcalibur"),
    ("Gimmighoul", "Gholdengo"),
    ("Poltchageist", "Sinistcha")
]

# Branching evolutions additions:
BRANCHING_EVOLUTIONS = {
    "Eevee": ["Vaporeon", "Jolteon", "Flareon", "Espeon", "Umbreon", "Leafeon", "Glaceon", "Sylveon"],
    "Gloom": ["Vileplume", "Bellossom"],
    "Poliwhirl": ["Poliwrath", "Politoed"],
    "Slowpoke": ["Slowbro", "Slowking"],
    "Tyrogue": ["Hitmonlee", "Hitmonchan", "Hitmontop"],
    "Wurmple": ["Silcoon", "Cascoon"],
    "Kirlia": ["Gardevoir", "Gallade"],
    "Snorunt": ["Glalie", "Froslass"],
    "Clamperl": ["Huntail", "Gorebyss"],
    "Applin": ["Flapple", "Appletun", "Dipplin"],
    "Charcadet": ["Armarouge", "Ceruledge"]
}


class EvolutionRegistry:
    def __init__(self):
        self.species_info: Dict[str, EvolutionInfo] = {}
        self.base_to_family: Dict[str, List[str]] = {}
        self._build_registry()

    def _determine_category(self, name: str, base_name: str) -> str:
        if name in LEGENDARIES or base_name in LEGENDARIES:
            return "legendary"
        if name in MYTHICALS or base_name in MYTHICALS:
            return "mythical"
        if name in ULTRA_BEASTS or base_name in ULTRA_BEASTS:
            return "ultra_beast"
        if name in PARADOX_POKEMON or base_name in PARADOX_POKEMON:
            return "paradox"
        if base_name in STARTER_FAMILIES:
            return "starter"
        return "regular"

    def _build_registry(self):
        for chain in EVOLUTION_CHAINS:
            base = chain[0]
            cat = self._determine_category(base, base)
            family = list(chain)

            # Check if base has branching options
            branch = BRANCHING_EVOLUTIONS.get(base, [])
            for b in branch:
                if b not in family:
                    family.append(b)

            self.base_to_family[base] = family

            for stage_idx, name in enumerate(chain):
                stage = stage_idx + 1
                prev_evo = chain[stage_idx - 1] if stage_idx > 0 else None
                next_evos = []

                if stage_idx + 1 < len(chain):
                    next_evos.append(chain[stage_idx + 1])

                if name in BRANCHING_EVOLUTIONS:
                    for b in BRANCHING_EVOLUTIONS[name]:
                        if b not in next_evos:
                            next_evos.append(b)

                self.species_info[name] = EvolutionInfo(
                    species_name=name,
                    base_species=base,
                    evolution_stage=stage,
                    evolves_from=prev_evo,
                    evolves_to=next_evos,
                    category=cat
                )

        # Connect branching nodes
        for parent, children in BRANCHING_EVOLUTIONS.items():
            if parent in self.species_info:
                p_info = self.species_info[parent]
                for child in children:
                    if child not in self.species_info:
                        self.species_info[child] = EvolutionInfo(
                            species_name=child,
                            base_species=p_info.base_species,
                            evolution_stage=p_info.evolution_stage + 1,
                            evolves_from=parent,
                            evolves_to=[],
                            category=p_info.category
                        )
                        if child not in self.base_to_family[p_info.base_species]:
                            self.base_to_family[p_info.base_species].append(child)

    def get_info(self, name: str) -> Optional[EvolutionInfo]:
        return self.species_info.get(name)

    def get_family(self, name: str) -> List[str]:
        info = self.get_info(name)
        if info:
            return self.base_to_family.get(info.base_species, [name])
        return [name]

    def sync_to_db(self, db_path: str = "data/processed/delugerpg_kb.db"):
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS pokemon_evolutions (
                species_name TEXT PRIMARY KEY NOT NULL,
                base_species TEXT NOT NULL,
                evolution_stage INTEGER NOT NULL,
                evolves_from TEXT,
                evolves_to TEXT,
                category TEXT NOT NULL
            );
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_evo_base ON pokemon_evolutions(base_species);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_evo_category ON pokemon_evolutions(category);")

        for name, info in self.species_info.items():
            cur.execute("""
                INSERT OR REPLACE INTO pokemon_evolutions (species_name, base_species, evolution_stage, evolves_from, evolves_to, category)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                info.species_name,
                info.base_species,
                info.evolution_stage,
                info.evolves_from,
                ",".join(info.evolves_to) if info.evolves_to else None,
                info.category
            ))
        conn.commit()
        conn.close()
