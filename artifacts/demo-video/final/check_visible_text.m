#import <Foundation/Foundation.h>
#import <Vision/Vision.h>
int main(int argc,const char *argv[]) {@autoreleasepool {
 int bad=0;
 for(int i=1;i<argc;i++) {@autoreleasepool {
  NSURL *url=[NSURL fileURLWithPath:[NSString stringWithUTF8String:argv[i]]];
  VNRecognizeTextRequest *request=[VNRecognizeTextRequest new];
  request.recognitionLevel=VNRequestTextRecognitionLevelAccurate;
  request.recognitionLanguages=@[@"zh-Hans",@"en-US"];
  VNImageRequestHandler *handler=[[VNImageRequestHandler alloc]initWithURL:url options:@{}];
  NSError *error=nil;
  if(![handler performRequests:@[request] error:&error]){fprintf(stderr,"OCR failed\n");return 2;}
  for(VNRecognizedTextObservation *result in request.results){
   NSString *text=[result topCandidates:1].firstObject.string;
   if([text containsString:@"参考号"]||[text.lowercaseString containsString:@"mocktr_"]||[text containsString:@"246810"]||[text.lowercaseString containsString:@"mockwealth_"]||[text containsString:@"Agent runtime failed"]){printf("Unexpected visible text: %s %s\n",argv[i],text.UTF8String);bad++;}
  }
 }}
 printf("Checked %d frames; unexpected reference/code text: %d\n",argc-1,bad);return bad?1:0;
}}
