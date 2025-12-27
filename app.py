#!/usr/bin/env python3
"""
Basic FastAnki Demo App
A simple demonstration of Answer.AI's fastanki library for managing Anki flashcards.
"""

from fastanki import add_card, find_notes, find_cards, Deck
from fastanki.core import Collection

def main():
    print("=" * 50)
    print("FastAnki Demo App")
    print("=" * 50)

    # Open a local Anki collection (creates "User 1" profile if needed)
    print("\n1. Opening Anki collection...")
    col = Collection.open()
    print("   Collection opened successfully!")

    # Show available decks
    print("\n2. Available decks:")
    for deck in col.decks.all():
        print(f"   - {deck['name']}")

    # Show available note types (models)
    print("\n3. Available note types:")
    for model in col.models.all():
        print(f"   - {model['name']}")

    # Add sample flashcards using the add_card function
    print("\n4. Adding sample flashcards...")
    add_card(
        Front="What is FastAnki?",
        Back="A Python library by Answer.AI for programmatically managing Anki flashcards.",
        tags=["demo", "fastanki"]
    )
    print("   Card 1 added!")

    add_card(
        Front="Who created FastAnki?",
        Back="Answer.AI (AnswerDotAI)",
        tags=["demo", "fastanki"]
    )
    print("   Card 2 added!")

    # Search for our cards
    print("\n5. Searching for cards with 'fastanki' tag...")
    notes = find_notes("tag:fastanki")
    print(f"   Found {len(notes)} note(s)")

    for note in notes:
        print(f"\n   Note ID: {note.id}")
        fields = dict(zip(note.keys(), note.values()))
        print(f"   Front: {fields.get('Front', 'N/A')}")
        print(f"   Back: {fields.get('Back', 'N/A')}")
        print(f"   Tags: {note.tags}")

    # Get collection stats (re-open since add_card manages its own collection)
    print("\n6. Collection stats:")
    col = Collection.open()
    card_count = col.card_count()
    note_count = col.note_count()
    print(f"   Total cards: {card_count}")
    print(f"   Total notes: {note_count}")

    # Create and use a Deck object
    print("\n7. Working with Deck object...")
    deck = Deck(col, "Default")
    print(f"   Deck '{deck.name}' has {len(deck.cards)} cards")

    # Close collection
    col.close()
    print("\n   Collection closed.")

    print("\n" + "=" * 50)
    print("Demo complete!")
    print("=" * 50)

    # Note about syncing
    print("\nTo sync with AnkiWeb, set ANKI_USER and ANKI_PASS environment variables")
    print("and call: sync()")

if __name__ == "__main__":
    main()
