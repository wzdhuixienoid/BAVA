#import <Cocoa/Cocoa.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <AVFoundation/AVFoundation.h>

@interface RecorderDelegate : NSObject <SCRecordingOutputDelegate>
@property(nonatomic, assign) BOOL finished;
@end
@implementation RecorderDelegate
- (void)recordingOutputDidStartRecording:(SCRecordingOutput *)output {
    printf("RECORDING %.3f\n",[[NSDate date] timeIntervalSince1970]);fflush(stdout);
}
- (void)recordingOutputDidFinishRecording:(SCRecordingOutput *)output {self.finished=YES;printf("FINISHED\n");fflush(stdout);}
- (void)recordingOutput:(SCRecordingOutput *)output didFailWithError:(NSError *)error {fprintf(stderr,"Recording failed: %s\n",error.localizedDescription.UTF8String);self.finished=YES;}
@end

int main(int argc,const char *argv[]) {@autoreleasepool {
    [NSApplication sharedApplication];
    if(argc<3){fprintf(stderr,"usage: native_recorder output.mp4 stop-file [seconds]\n");return 1;}
    NSString *outputPath=[NSString stringWithUTF8String:argv[1]];
    NSString *stopPath=[NSString stringWithUTF8String:argv[2]];
    double seconds=argc>3?atof(argv[3]):1200;
    __block SCShareableContent *content=nil;__block NSError *failure=nil;__block BOOL ready=NO;
    [SCShareableContent getShareableContentExcludingDesktopWindows:YES onScreenWindowsOnly:NO completionHandler:^(SCShareableContent *c,NSError *e){content=c;failure=e;ready=YES;}];
    while(!ready)[[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.02]];
    if(failure){fprintf(stderr,"Capture unavailable: %s\n",failure.localizedDescription.UTF8String);return 2;}
    NSMutableArray<SCWindow *> *matches=[NSMutableArray array];
    for(SCWindow *w in content.windows)if([w.owningApplication.bundleIdentifier isEqualToString:@"com.microsoft.edgemac"]&&[w.title containsString:@"AI 银行助理"]) [matches addObject:w];
    if(matches.count!=1){fprintf(stderr,"Expected exactly one BAVA window; found %lu\n",(unsigned long)matches.count);for(SCWindow *w in content.windows)if([w.owningApplication.applicationName containsString:@"Edge"])fprintf(stderr,"Edge: %s %s\n",w.owningApplication.bundleIdentifier.UTF8String,w.title.UTF8String);return 3;}
    SCWindow *window=matches.firstObject;
    SCContentFilter *filter=[[SCContentFilter alloc]initWithDesktopIndependentWindow:window];
    SCStreamConfiguration *config=[SCStreamConfiguration new];
    printf("WINDOW %.0f %.0f\n",window.frame.size.width,window.frame.size.height);fflush(stdout);
    config.sourceRect=CGRectMake(4,125,1504,815);
    config.width=3008;config.height=1630;
    config.minimumFrameInterval=CMTimeMake(1,30);
    config.capturesAudio=NO;config.showsCursor=YES;
    config.ignoreShadowsSingleWindow=YES;config.queueDepth=6;
    SCStream *stream=[[SCStream alloc]initWithFilter:filter configuration:config delegate:nil];
    SCRecordingOutputConfiguration *recordConfig=[SCRecordingOutputConfiguration new];
    recordConfig.outputURL=[NSURL fileURLWithPath:outputPath];
    recordConfig.videoCodecType=AVVideoCodecTypeH264;recordConfig.outputFileType=AVFileTypeMPEG4;
    RecorderDelegate *delegate=[RecorderDelegate new];
    SCRecordingOutput *record=[[SCRecordingOutput alloc]initWithConfiguration:recordConfig delegate:delegate];
    NSError *error=nil;
    if(![stream addRecordingOutput:record error:&error]){fprintf(stderr,"Output error: %s\n",error.localizedDescription.UTF8String);return 4;}
    __block BOOL started=NO;
    [stream startCaptureWithCompletionHandler:^(NSError *e){failure=e;started=YES;}];
    while(!started)[[NSRunLoop currentRunLoop]runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.02]];
    if(failure){fprintf(stderr,"Start error: %s\n",failure.localizedDescription.UTF8String);return 5;}
    NSDate *start=[NSDate date];
    while(![[NSFileManager defaultManager]fileExistsAtPath:stopPath]&&-[start timeIntervalSinceNow]<seconds&&!delegate.finished)
        [[NSRunLoop currentRunLoop]runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.05]];
    __block BOOL stopped=NO;[stream stopCaptureWithCompletionHandler:^(NSError *e){stopped=YES;}];
    while(!stopped||!delegate.finished)[[NSRunLoop currentRunLoop]runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.02]];
    return 0;
}}
