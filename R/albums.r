read.albums <- function(path) {
    albums <- read.delim(path, sep=",", stringsAsFactors=FALSE, header=TRUE)
    albums$AlbumLoved <- ifelse(albums$AlbumLoved == "y", TRUE, FALSE)
    albums$FracLoved <- albums$NumLovedTracks / albums$NumTracks

    return(albums)
}
