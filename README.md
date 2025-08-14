# AV-Converter
音视频格式转换是一个常见的需求。然而，大多数格式转换工具依赖在线服务，存在数据安全风险。为解决这一问题，本人开发了 AV Converter，一款高效、安全的本地音视频格式转换软件。
(Audio and video format conversion is a common need. Most tools rely on online services with data security risks. To solve this, I developed AV Converter—a local, efficient, and secure conversion software.)
- 视频格式转换(mp4、webm、mkv、mp3、wav、mov)
- 编辑视频分辨率(1080p、4K、2K、720p、保持原分辨率、自定义)
- 更改视频编码(libx264、libx265、vp9、复制)
- 修改音频编码(aac、libmp3lame、opus、复制)
- 修改视频 CRF/质量(适用于 x264/x265/vp9)

**音视频格式转换列表**  
webm转mp4，webm转mov，mov转mp4，mp4转webm，mp4转mov，mkv转mp4，mkv转webm，mkv转mov，wav转mp3，mov转webm，mp4转mkv，webm转mkv，wav转mov。
音频提取，视频大小压缩。

**本地运行**  
音视频文件格式转换和压缩大小均在本地电脑运行，保证数据安全。安装完成依赖后可直接双击dist目录下exe文件运行。程序运行速度取决于电脑cpu配置。处理1080p视频可做到1比一处理速度。

**友好的GUI**  
可视化界面可以选择各种参数。

**注意**  
需要调整视频分辨率时，音视频编码不能选择copy。默认编码为libx264（视频），aac（音频）。视频crf质量默认值为23，其中 0 是无损，值越大画质损失大。
