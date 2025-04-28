FROM amazonlinux:2

# Install Python and development tools
RUN yum update -y && \
    yum install -y python3 python3-pip python3-devel \
    gcc gcc-c++ make openssl-devel zip git

# Create directory for building packages
WORKDIR /build
COPY requirements.txt ./

# Run the build script
CMD ["bash", "-c", "pip3 install -r requirements.txt && cp -r /build /output"]