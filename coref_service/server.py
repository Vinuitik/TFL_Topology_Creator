from __future__ import annotations

import logging
import concurrent.futures

import grpc
import spacy

import coref_pb2
import coref_pb2_grpc

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_nlp = None


def _get_nlp():
    global _nlp
    if _nlp is None:
        log.info("Loading spaCy model en_core_web_lg (CPU)")
        _nlp = spacy.load("en_core_web_lg")
        _nlp.add_pipe("coreferee")
        log.info("coreferee model loaded")
    return _nlp


def _resolve(text: str) -> str:
    nlp = _get_nlp()
    doc = nlp(text)

    if not doc._.has("coref_chains") or doc._.coref_chains is None:
        return text

    replacements: list[tuple[int, int, str]] = []

    for chain in doc._.coref_chains:
        mentions = [chain[i] for i in range(len(chain))]
        if not mentions:
            continue

        canonical_mention = max(mentions, key=lambda m: len(m))
        canonical_tokens = [doc[idx] for idx in canonical_mention]
        canonical = doc[canonical_tokens[0].i : canonical_tokens[-1].i + 1].text

        for mention in mentions:
            tokens = [doc[idx] for idx in mention]
            span = doc[tokens[0].i : tokens[-1].i + 1]
            if span.text == canonical:
                continue
            replacements.append((span.start_char, span.end_char, canonical))

    if not replacements:
        return text

    replacements.sort(key=lambda x: x[0], reverse=True)
    chars = list(text)
    for start, end, repl in replacements:
        chars[start:end] = list(repl)
    return "".join(chars)


class CoreferenceServicer(coref_pb2_grpc.CoreferenceServiceServicer):
    def Resolve(self, request, context):
        try:
            resolved = _resolve(request.text)
            return coref_pb2.ResolveResponse(resolved_text=resolved)
        except Exception as exc:
            log.exception("Resolve failed")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(exc))
            return coref_pb2.ResolveResponse()


def serve():
    server = grpc.server(concurrent.futures.ThreadPoolExecutor(max_workers=4))
    coref_pb2_grpc.add_CoreferenceServiceServicer_to_server(CoreferenceServicer(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    log.info("coref-service listening on :50051")
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
