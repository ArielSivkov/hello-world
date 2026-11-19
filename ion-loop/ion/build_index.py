"""Build an offline search index (SQLite FTS5) from a Hebrew Wikipedia parquet snapshot.

  python3 -m ion.build_index <dir with *.parquet> <out.db>

Snapshot: https://huggingface.co/datasets/wikimedia/wikipedia  (20231101.he, CC BY-SA)
"""
import glob
import sqlite3
import sys

import pyarrow.parquet as pq


def main(src, out):
    db = sqlite3.connect(out)
    db.execute("drop table if exists docs")
    db.execute("create virtual table docs using fts5(title, body, url unindexed, tokenize='unicode61 remove_diacritics 2')")
    n = 0
    for f in sorted(glob.glob(src + "/*.parquet")):
        pf = pq.ParquetFile(f)
        for batch in pf.iter_batches(batch_size=2000, columns=["title", "text", "url"]):
            d = batch.to_pydict()
            rows = [(t, " ".join(x[:900].split()), u) for t, x, u in zip(d["title"], d["text"], d["url"])
                    if x and len(x) > 200]
            db.executemany("insert into docs values (?,?,?)", rows)
            n += len(rows)
        db.commit()
        print(f, n, flush=True)
    db.execute("create table if not exists tidx(title text, rid integer)")
    db.execute("delete from tidx")
    db.execute("insert into tidx select title, rowid from docs")      # exact-title lookups
    db.execute("create index if not exists tidx_t on tidx(title)")
    db.execute("insert into docs(docs) values ('optimize')")
    db.commit()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
