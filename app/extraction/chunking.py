from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptSegment:
    id: int
    speaker: str
    text: str
    char_start: int = 0

    @property
    def char_end(self) -> int:
        return self.char_start + len(self.text)


@dataclass(frozen=True)
class ExtractionChunk:
    text: str
    segments: tuple[TranscriptSegment, ...]


def build_chunks(
    segments: list[TranscriptSegment],
    max_chars: int = 3500,
    overlap_segments: int = 1,
) -> list[ExtractionChunk]:
    """Group segments without losing their source metadata.

    The overlap is expressed in whole segments, so evidence can always be
    mapped back to a known source segment instead of an opaque model chunk.
    """
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if overlap_segments < 0:
        raise ValueError("overlap_segments cannot be negative")

    chunks: list[ExtractionChunk] = []
    start = 0
    while start < len(segments):
        end = start
        size = 0
        while end < len(segments):
            segment_size = len(segments[end].text)
            if end > start and size + segment_size > max_chars:
                break
            size += segment_size
            end += 1

        selected = tuple(segments[start:end])
        chunks.append(ExtractionChunk("\n".join(segment.text for segment in selected), selected))
        if end >= len(segments):
            break
        start = max(start + 1, end - overlap_segments)

    return chunks
