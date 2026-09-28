"""Answer intent and task-focused evidence selection, independent of source routing."""
import re
from dataclasses import replace


def answer_intent(question):
    q = question.lower()
    if re.search(r'\b(how (?:do|can|should|to)|process|procedure|steps|workflow)\b', q):
        return 'procedure'
    if re.search(r'\b(pending|outstanding|open action|unresolved)\b', q):
        return 'pending'
    if re.search(r'\b(who|owner|ownership)\b', q):
        return 'ownership'
    if re.search(r'\b(when|how often|frequency|deadline)\b', q):
        return 'timing'
    if re.search(r'\b(tasks?|responsibilities|duties|role)\b', q):
        return 'responsibility'
    return 'general'


PROCESS = re.compile(r'\b(process|procedure|steps?|workflow|actions?|follow.up|submit\w*|review\w*|approv\w*|monitor\w*|escalat\w*|request\w*|prepar\w*|include\w*|enter\w*|select\w*|click\w*|send\w*|creat\w*)\b', re.I)
STOP = set('how do does i we can should to a an the is are what for of in you check anything mentioned please tell me about creating processing create make submit approve get procedure step steps process perform carry out'.split())


def words(text):
    text = re.sub(r'\bchange[ -]+notes?\b', 'change order', text, flags=re.I)
    return {w[:-1] if len(w) > 3 and w.endswith('s') and not w.endswith('ss') else w
            for w in re.findall(r'[a-z0-9]+', text.lower())}


def focused_procedures(chunks, question):
    terms = words(question) - STOP
    if not terms:
        return []
    ranked = []
    for rc in chunks:
        heading = rc.chunk.section or ''
        parts = re.split(r'\n\s*\n|(?<=[.!?])(?<!\d\.)\s+(?=[A-Z])', rc.chunk.content)
        direct = []
        active_heading = heading
        for part in parts:
            if re.match(r'^\d+\.\s+[A-Z]', part):
                active_heading = part
            if (terms <= words(active_heading + ' ' + part) and PROCESS.search(part)
                    and not re.search(r'\b(responsibilities|duties)\s+(include|are)\b', part, re.I)):
                direct.append(part)
        if not direct:
            continue
        # Keep adjacent field lists only under an explicit procedure/requirements lead-in.
        for index, part in enumerate(parts):
            if part in direct and re.search(r'\b(include|following|required|steps)\b.*:?\s*$', part, re.I):
                for following in parts[index + 1:index + 8]:
                    if re.match(r'^\d+\.\s+[A-Z]', following):
                        break
                    if len(following.split()) > 15:
                        break
                    direct.append(following)
        content = '\n\n'.join(dict.fromkeys(direct))
        rank = (3 if terms <= words(heading) else 0) + len(PROCESS.findall(content))
        ranked.append((rank, replace(rc, chunk=replace(rc.chunk, content=content))))
    return [rc for _, rc in sorted(ranked, key=lambda pair: pair[0], reverse=True)][:8]


def retrieval_question(question):
    if answer_intent(question) == 'procedure':
        return question + ' procedure steps workflow submit review approve monitor escalate follow-up'
    return question


def answer_rules(question):
    intent = answer_intent(question)
    common = ('Answer the exact question first, concisely, using retrieved evidence only. '
              'Cite each important claim or step with its supplied [S#] citation. '
              'Do not add related responsibilities merely because they share topic keywords. '
              'Expand only if requested. ')
    rules = {
        'procedure': ('Provide only actions explicitly linked by the source to the requested process. '
            'Separate direct procedural evidence from background information; omit the background unless requested. '
            'Do not turn a process question into a list of responsibilities. Never infer missing steps, ordering, '
            'prerequisites or dependencies from general knowledge. If a complete end-to-end procedure is not '
            'explicitly documented, begin exactly: "The meeting documents do not provide a complete end-to-end procedure." '
            'Distinguish documented procedure steps, historical process information, current responsibilities/ownership, '
            'and related contextual information. Use numbered steps only when retrieved evidence explicitly establishes '
            'their order or dependency. Never infer a workflow sequence from the order of facts in a retrieved chunk, '
            'the ranking of chunks, or facts appearing in different sources. Independent supported actions may be '
            'described with unnumbered bullets, without implying sequence. If activities were historically performed, '
            'describe them as "historically involved", not as current instructions or Step 1, Step 2, Step 3. '
            'Historical ownership is not evidence of current ownership. Preserve temporal qualifiers, conditions, '
            'and citations for each claim. Do not turn "create the requested item" into a step explaining how to create it. '
            'Related processes are steps only when the source explicitly establishes the dependency. '
            'If there are no documented procedure steps, say so; label any relevant historical information separately.'),
        'responsibility': 'List only documented tasks/responsibilities for the requested person or role; do not invent a workflow.',
        'pending': 'List only explicitly open or unresolved actions. Do not treat routine duties as pending. State that historical status may not be current.',
        'ownership': 'Name only the explicitly documented owner of the requested activity. Mentioning a person is not evidence of ownership.',
        'timing': 'Give only the documented date, deadline or frequency for the requested activity. Do not infer a schedule.',
    }
    return common + rules.get(intent, '')
