def test_bulk_delete_selected_and_all(client):
    ids = [client.post("/api/groups", json={"name": f"Г-{i}", "size": 20, "shift": "утро"}).json()["id"] for i in range(5)]
    r = client.post("/api/bulk-delete/groups", json={"ids": ids[:2]})
    assert r.json()["deleted"] == 2
    assert {g["id"] for g in client.get("/api/groups").json()} == set(ids[2:])
    assert client.post("/api/bulk-delete/groups", json={"all": True}).json()["deleted"] == 3
    assert client.get("/api/groups").json() == []
    assert client.post("/api/bulk-delete/unknown", json={"all": True}).status_code == 404


def test_bulk_delete_teachers_with_subjects(client):
    s = client.post("/api/subjects", json={"name": "Физика", "lesson_type": "лекция", "room_type": "обычная"}).json()
    t = client.post("/api/teachers", json={"full_name": "Иванов И.И.", "subject_ids": [s["id"]]}).json()
    assert client.post("/api/bulk-delete/teachers", json={"ids": [t["id"]]}).json()["deleted"] == 1
    assert client.get("/api/subjects").json()  # дисциплина осталась
