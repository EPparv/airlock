// This fixed local program reads filtered passages from stdin and returns numbers only.
ObjC.import('Foundation');
ObjC.import('NaturalLanguage');

function run() {
  const bytes = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
  const input = JSON.parse(ObjC.unwrap($.NSString.alloc.initWithDataEncoding(bytes, $.NSUTF8StringEncoding)));
  const embedding = $.NLEmbedding.sentenceEmbeddingForLanguage('en');
  if (!embedding || embedding.isNil()) return 'null';

  const cosine = 0; // NLDistanceTypeCosine in the system framework.
  const scores = input.passages.map(function (passage) {
    const distance = embedding.distanceBetweenStringAndStringDistanceType(input.query, passage, cosine);
    return Math.max(-1, Math.min(1, 1 - distance));
  });
  return JSON.stringify(scores);
}
