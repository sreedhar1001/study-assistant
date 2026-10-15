Living Study Guide

A private study app that turns your own notes into flashcards and quiz questions, with a human approving every AI-written item before it counts.

Why this exists

AI can write study material quickly, but it can also invent facts you would then memorize. This app keeps the source next to what the AI wrote and puts you in charge: nothing enters your library until you approve it.

How it works
Add your notes. Paste your own notes and save them under a topic (for example, Photosynthesis).
Generate drafts. The AI proposes flashcards or quiz questions using only the text of your notes.
Review. Each draft waits in a pending queue beside the sentence it came from. You approve, edit, or reject it.
Approved library. Approved cards are saved to a private, searchable library that persists between sessions.
Quiz yourself. Quizzes draw only from approved items.
Features
Source-grounded generation: drafts are based only on your notes
Human-in-the-loop approval: AI output stays pending until you accept it
Saved data: your notes and approved cards are kept from session to session
Private by design: sign in to see your own library
Searchable library of approved flashcards and quiz questions
Built with
Built and hosted on Replit
An OpenAI model for generating drafts (gpt-4o-mini)
A database for saved notes and approved cards

Update this list if your stack differs.

Setup
Clone the repository or import it into Replit.
Add your API key as a secret named OPENAI_API_KEY. In Replit, use the Secrets tool.
Install dependencies and run the app (in Replit, press Run).

Never put your API key in the code or commit it to GitHub. Keep it in environment variables or Secrets only.

Example notes to try

Paste a short passage of your own, such as a few sentences on photosynthesis, then click Generate flashcards. To test grounding, leave out one detail on purpose and check that the AI does not fill the gap with facts you never wrote.

Known limitations
Draft quality depends on the quality and clarity of your notes.
Generation needs an API key with available credits.
Always review drafts. The approval step exists because the AI can still make mistakes.
Roadmap ideas
Upload notes from PDFs or documents
Spaced-repetition scheduling for flashcards
Tags and filters by topic
Export approved cards
License

Add a license of your choice (for example MIT) before sharing publicly.
