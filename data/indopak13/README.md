# IndoPak 13-line (Qudratullah) layout

**QUL bundle folder** can contain:

| File | Role |
|------|------|
| `indopak-13-lines-layout-qudratullah.db` | Layout (`pages`) |
| `indopak-nastaleeq.db.zip` or `indopak-nastaleeq.db` | Words (`id` = global word index, matches layout ranges) |
| `wordbyword.zip` | 849× .docx proofs only — **not** used by import |

From project root, if that folder sits at `indopak-13-lines-layout-qudratullah.db/`:

```bash
py -3 scripts/import_indopak13_qudratullah.py indopak-13-lines-layout-qudratullah.db
```

The script unzips `indopak-nastaleeq.db.zip` into `_nastaleeq_extract/` when needed.

Or pass two `.db` paths manually. Run `py -3 scripts/check_indopak_db.py your.db` to see tables.

Output:

- `pages/1.json` … `pages/849.json`
- `surah_start_pages.json`

**App:** Settings → **IndoPak 13-line Qudratullah (849 p.)** (reloads when toggled).
