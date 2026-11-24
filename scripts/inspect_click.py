with open('DELUGERPG_Consolidated_Reference/DELUGERPG_MASTER_REFERENCE.md', 'r', encoding='utf-8') as f:
    text = f.read()

target = '$("#directions a").click('
idx = text.find(target)
if idx != -1:
    print(text[idx:idx+1200])
else:
    print("Not found")
