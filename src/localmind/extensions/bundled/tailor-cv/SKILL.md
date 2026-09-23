---
name: tailor-cv
description: Tailor a LaTeX CV to one job description and compile it to PDF. Use for any request to adapt, rewrite or target a CV or résumé at a job listing.
---
# Tailoring a CV to a job

Work through these steps in order. Don't ask the user questions: make sensible choices and say
what you did at the end.

1. **Read the job.** Pull out the employer, the role title, the five or six requirements that
   matter most, and the words they use for them (tools, skills, domains).
2. **Get the CV source.** Use knowledge_search to find the CV, then open_document to load the
   complete original `.tex`. Always start from the original, never from memory.
3. **Tailor it, truthfully.**
   - Never invent employers, dates, grades, numbers or skills. Only reorder, cut, merge and reword
     what is already there. If the job asks for something the CV lacks, leave it out.
   - Lead each section with the experience closest to the job's requirements; cut or shorten what
     is irrelevant.
   - Rewrite bullets to use the job's own terms where they honestly apply, starting with a strong
     past-tense verb and ending with a concrete result (a number where the CV has one).
   - Adjust the profile or summary (two or three lines) to this role and employer.
   - Make real edits, not a token one: rewrite the profile for this employer, and rewrite at least
     three bullets so they lead with what this job asks for. Keep every role unless it is plainly
     irrelevant; shorten it rather than delete it.
   - Keep the original layout, packages and length. A one-page CV stays one page.
4. **Write it plainly.** British English (organised, analysed, programme). None of: "passionate",
   "results-driven", "proven track record", "team player", "leverage", "spearheaded", "delve",
   "dynamic". No bold phrases inside bullets, no em dashes where a comma will do.
5. **Save and compile.** write_file as `cv-<employer>.tex` (lower case, hyphens), then
   compile_latex. If it fails, read the errors, fix the file, and compile again. Escape LaTeX
   specials you introduce (`&`, `%`, `$`, `#`, `_`).
6. **Report back** in three to five sentences: which role this targets, the main changes, and
   anything in the job the CV doesn't cover (so the user can decide whether to add it). Describe
   only changes that are really in the file you saved (write_file tells you its path; read it back
   with read_file if unsure). Never claim an edit you didn't make.
