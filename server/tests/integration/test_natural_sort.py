import json
import subprocess

from sqlalchemy import Engine, String, literal, select, union_all

from app.db.natural_sort import natural_sort_keys


def test_natural_sort_matches_chinese_numeric_collator(test_database_engine: Engine) -> None:
    values = [
        "工厂１０",
        "工厂２",
        "工厂٠٢",
        "工厂10",
        "工厂2",
        "工厂02",
        "工厂1",
        "禹帆",
        "盛峰",
        "聚兴",
        "A2",
        "a10",
        "A10",
        "a2",
        "",
        "—",
        "张2、王10",
        "张2、王2",
        "é2",
        "e10",
        "e2",
    ]
    projection = union_all(
        *[
            select(literal(i).label("id"), literal(value, type_=String()).label("value"))
            for i, value in enumerate(values)
        ]
    ).subquery()
    keys = natural_sort_keys(select(projection.c.id, projection.c.value), name="test_sort")
    expected = json.loads(
        subprocess.check_output(
            [
                "node",
                "-e",
                "const a=JSON.parse(process.argv[1]);"
                " console.log(JSON.stringify(a.map((v,i)=>({v,i}))"
                ".sort((a,b)=>a.v.localeCompare(b.v,'zh-CN',{numeric:true})).map(x=>x.i)))",
                json.dumps(values),
            ]
        )
    )
    with test_database_engine.connect() as connection:
        actual = list(connection.scalars(select(keys.c.id).order_by(keys.c.sort_key, keys.c.id)))
    assert actual == expected, [values[i] for i in actual]
