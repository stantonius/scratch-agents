#!/usr/bin/env python3
"""
FastAnki Web App
A web interface for managing Anki flashcards using FastHTML and fastanki.
"""

from fasthtml.common import *
from fastanki import add_card, find_notes, del_card, update_note, Deck
from fastanki.core import Collection

app, rt = fast_app(
    hdrs=(
        Style("""
            body { font-family: system-ui, -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
            h1 { color: #2563eb; }
            .card { background: white; border-radius: 8px; padding: 20px; margin: 10px 0; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .card-front { font-weight: bold; font-size: 1.1em; margin-bottom: 10px; }
            .card-back { color: #666; border-top: 1px solid #eee; padding-top: 10px; }
            .tags { margin-top: 10px; }
            .tag { background: #e0e7ff; color: #3730a3; padding: 2px 8px; border-radius: 4px; font-size: 0.85em; margin-right: 5px; }
            form { background: white; padding: 20px; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            input, textarea { width: 100%; padding: 10px; margin: 5px 0 15px 0; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }
            button { background: #2563eb; color: white; padding: 10px 20px; border: none; border-radius: 4px; cursor: pointer; }
            button:hover { background: #1d4ed8; }
            .delete-btn { background: #dc2626; padding: 5px 10px; font-size: 0.85em; }
            .delete-btn:hover { background: #b91c1c; }
            .stats { background: #dbeafe; padding: 15px; border-radius: 8px; margin-bottom: 20px; }
            .nav { margin-bottom: 20px; }
            .nav a { margin-right: 15px; color: #2563eb; text-decoration: none; }
            .nav a:hover { text-decoration: underline; }
            .study-card { text-align: center; padding: 40px; }
            .study-card .front { font-size: 1.5em; margin-bottom: 20px; }
            .study-card .back { font-size: 1.2em; color: #666; padding: 20px; background: #f0f0f0; border-radius: 8px; margin: 20px 0; }
            .hidden { display: none; }
            .btn-group { display: flex; gap: 10px; justify-content: center; margin-top: 20px; }
        """),
    ),
)

def get_stats():
    col = Collection.open()
    stats = {"cards": col.card_count(), "notes": col.note_count()}
    col.close()
    return stats

def get_all_notes():
    return find_notes("")

@rt("/")
def get():
    stats = get_stats()
    notes = get_all_notes()

    cards_html = []
    for note in notes:
        fields = dict(zip(note.keys(), note.values()))
        tags_html = [Span(t, cls="tag") for t in note.tags] if note.tags else []
        cards_html.append(
            Div(
                Div(fields.get('Front', 'No front'), cls="card-front"),
                Div(fields.get('Back', 'No back'), cls="card-back"),
                Div(*tags_html, cls="tags") if tags_html else None,
                Form(
                    Button("Delete", cls="delete-btn", type="submit"),
                    method="post",
                    action=f"/delete/{note.id}",
                    style="margin-top: 10px;",
                ),
                cls="card",
            )
        )

    return Title("FastAnki"), Main(
        H1("FastAnki Web App"),
        Div(
            A("Home", href="/"),
            A("Add Card", href="/add"),
            A("Study", href="/study"),
            cls="nav",
        ),
        Div(
            P(f"Total Cards: {stats['cards']} | Total Notes: {stats['notes']}"),
            cls="stats",
        ),
        H2("Your Flashcards"),
        Div(*cards_html) if cards_html else P("No cards yet. Add some!"),
    )

@rt("/add")
def get():
    return Title("Add Card - FastAnki"), Main(
        H1("Add New Flashcard"),
        Div(
            A("Home", href="/"),
            A("Add Card", href="/add"),
            A("Study", href="/study"),
            cls="nav",
        ),
        Form(
            Label("Front:"),
            Textarea(name="front", placeholder="Question or prompt...", rows=3),
            Label("Back:"),
            Textarea(name="back", placeholder="Answer...", rows=3),
            Label("Tags (comma-separated):"),
            Input(name="tags", placeholder="e.g., python, programming"),
            Button("Add Card", type="submit"),
            method="post",
            action="/add",
        ),
    )

@rt("/add")
def post(front: str, back: str, tags: str = ""):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()]
    add_card(Front=front, Back=back, tags=tag_list if tag_list else None)
    return RedirectResponse("/", status_code=303)

@rt("/delete/{note_id}")
def post(note_id: int):
    del_card(note_id)
    return RedirectResponse("/", status_code=303)

@rt("/study")
def get():
    notes = get_all_notes()
    if not notes:
        return Title("Study - FastAnki"), Main(
            H1("Study Mode"),
            Div(
                A("Home", href="/"),
                A("Add Card", href="/add"),
                A("Study", href="/study"),
                cls="nav",
            ),
            P("No cards to study. Add some first!"),
        )

    # Get first card for study
    note = notes[0]
    fields = dict(zip(note.keys(), note.values()))

    return Title("Study - FastAnki"), Main(
        H1("Study Mode"),
        Div(
            A("Home", href="/"),
            A("Add Card", href="/add"),
            A("Study", href="/study"),
            cls="nav",
        ),
        Div(
            Div(fields.get('Front', 'No front'), cls="front"),
            Div(fields.get('Back', 'No back'), cls="back hidden", id="answer"),
            Div(
                Button("Show Answer", onclick="document.getElementById('answer').classList.remove('hidden'); this.style.display='none'; document.getElementById('next-btns').style.display='flex';"),
                cls="btn-group",
            ),
            Div(
                A(Button("Next Card"), href="/study"),
                A(Button("Back to Cards"), href="/"),
                cls="btn-group hidden",
                id="next-btns",
            ),
            cls="card study-card",
        ),
        Script("""
            // Shuffle cards on page load for variety
        """),
    )

serve(port=5001)
