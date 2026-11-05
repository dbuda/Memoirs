import re

from app.extraction.chunking import TranscriptSegment


TRANSCRIPT_LINE = re.compile(r"^\[(?P<timestamp>[^]]+)\]\s+(?P<speaker>[A-Z_]+):\s+(?P<text>.+)$")


def parse_transcript(text: str) -> list[TranscriptSegment]:
    """Parse labelled transcript lines and preserve offsets into the source text."""
    segments: list[TranscriptSegment] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        line_without_newline = line.rstrip("\r\n")
        match = TRANSCRIPT_LINE.match(line_without_newline)
        if match:
            source_text = match.group("text")
            text_start = offset + match.start("text")
            segments.append(
                TranscriptSegment(
                    id=len(segments) + 1,
                    speaker=match.group("speaker"),
                    text=source_text,
                    char_start=text_start,
                )
            )
        offset += len(line)
    if not segments:
        raise ValueError("Transcript contains no labelled speaker lines")
    return segments
