# Shared by the privacy hooks (pre-commit, commit-msg, pre-push). Sourced, never run by itself.
# Every hook sets $hook to its own name first, for the messages.

# Sets $terms to the private-terms list, or stops the hook: no list, or a path that has gone missing, would let
# the scan fall back to another list, or to none.
need_terms() {
    terms=$(git config --get reverse-recruiter.privateTerms)
    if [ -z "$terms" ]; then
        echo "$hook: set your private-terms list first:"
        echo "  git config reverse-recruiter.privateTerms \"<path to private-terms.txt>\""
        exit 1
    fi
    if [ ! -f "$terms" ]; then
        echo "$hook: the private-terms list is missing: $terms"
        echo "  Fix the path: git config reverse-recruiter.privateTerms \"<path to private-terms.txt>\""
        exit 1
    fi
    if [ ! -f engine/privacy_scan.py ]; then
        echo "$hook: engine/privacy_scan.py is missing; can't run the privacy check."
        exit 1
    fi
}

# Reads file names (one per line); prints those that are personal-data paths: a personal-data folder by name, a
# private-terms list, or the data-folder layout under any name except the fictional sample-data/.
# Names are matched without regard to case: on Windows and macOS "My-Data/" is the same folder as "my-data/".
personal_paths() {
    names=$(cat)
    printf '%s\n' "$names" | grep -iE '(^|/)(my-data|private-data)/|private-terms\.txt$|\.private\.|CLAUDE\.local\.md$'
    printf '%s\n' "$names" | grep -iE '(^|/)(1-inbox|2-reports|3-applications|4-profile|5-criteria|6-system|7-recommendations|8-mentor-advice|9-learning)/' | grep -vE '^sample-data/'
    return 0
}

# Reads file names; prints the document formats the text scan can't read (resumes, saved postings, exports).
document_paths() {
    grep -iE '\.(pdf|docx?|rtf|odt|xlsx?|pptx?|msg|eml)$'
    return 0
}
