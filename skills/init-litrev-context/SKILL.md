---
name: init-litrev-context
description: Collaboratively set up project context for tailored literature review responses. Use when user wants to initialize, update, or refine the context for a litrev project. The context (goal, audience, style) will be used to tailor responses from ask_papers, analyze_insights, and other tools. Invoke with project code as argument, or prompt for project if not provided.
---

# Initialize Literature Review Context

Guide a collaborative conversation to set up project context for tailored responses.

## Approach

Be conversational, not formulaic. This is a dialogue where users may:
- Think out loud about unclear goals
- Ask follow-up questions about what you mean
- Be unsure about their direction
- Want your perspective on scope/approach

## Flow

1. **Check existing**: Call `get_project_context` for the project
   - If exists: Offer to refine/update vs start fresh
   - If missing: Begin collaborative setup

2. **Explore through conversation**:
   - **Goal**: What are you trying to accomplish? (dissertation chapter, systematic review, grant proposal, journal article...)
   - **Audience**: Who will read this? What's their background? (committee, journal reviewers, practitioners, general academic...)
   - **Style**: What tone/format is appropriate? (technical, accessible, formal, narrative...)
   - **Key questions**: What are you trying to answer?

3. **Add value during the conversation**:
   - Offer thoughts on scope
   - Suggest considerations they might not have thought of
   - Help them clarify fuzzy ideas
   - Share relevant perspective on their field

4. **Synthesize**: When enough context is gathered:
   - Draft a `_context.md` based on the conversation
   - Show the draft to the user
   - Refine based on feedback

5. **Save**: Call `update_project_context` when the user approves

## Opening Example

"Let's set up context for [PROJECT] so I can better tailor my responses when we work on this literature review. Tell me about this project - what are you ultimately trying to accomplish with it?"

## Guidelines

- Let the conversation breathe - don't rush through questions
- Tangents are fine if they help clarify thinking
- Offer your perspective when relevant - you're a collaborator, not just a form
- The goal is useful context, not perfect documentation
- If they're unsure, help them figure it out rather than pressing for answers

## Context File Template

The `_context.md` file should follow this general structure:

```markdown
# {Project Name} Context

## Goal
[What this literature review is trying to accomplish]

## Audience
[Who will read/use this work and their background]

## Style
[Writing style, tone, format preferences]

## Key Questions
[Core questions driving the review]

## Notes
[Additional context, constraints, or evolution notes]

---
*Last updated: {date}*
```
