"""Shared stable-ID delivery for web and explicit chat publication."""


def deliver_publication(api, row):
    response = api.client.get("/api/v1/chat.getMessage", params={"msgId": row.message_id})
    if response.status_code == 200 and response.json().get("message"):
        msg = response.json()["message"]
    elif response.status_code in (400, 404) and (response.json().get("errorType") in
            ("error-invalid-message", "error-message-not-found") or response.json() == {"success": False}):
        msg = api.call("POST", "chat.sendMessage", {"message": {"_id": row.message_id,
            "rid": row.room_id, "msg": row.text}, "previewUrls": []})["message"]
    else:
        raise RuntimeError("Cannot verify publication message")
    if msg.get("rid") != row.room_id or msg.get("msg") != row.text or msg.get("u", {}).get("_id") != api.user_id:
        raise RuntimeError("Publication receipt mismatch")
